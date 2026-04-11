"""
DepthGuard - Mini servidor para test de Push Notifications

Uso:
    cd scripts
    ..\venv\Scripts\python.exe servidor_push_test.py

    (luego en otra terminal: ngrok http 3000)
"""

import json
import base64
import traceback
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pywebpush import webpush, WebPushException
from py_vapid import Vapid

import uvicorn

# ─── Configuración ────────────────────────────────────────
KEYS_FILE = Path(__file__).parent / "vapid_keys.json"
PORT = 3000

app = FastAPI()

# ─── Generar/Cargar claves VAPID ─────────────────────────
# Usamos py_vapid directamente para evitar problemas de serialización

if KEYS_FILE.exists():
    with open(KEYS_FILE, "r") as f:
        saved_keys = json.load(f)
    # Recrear el objeto Vapid desde la clave pública guardada
    vapid_obj = Vapid.from_raw(saved_keys["privateKeyRaw"].encode("utf-8"))
    public_key_b64 = saved_keys["publicKey"]
    print("🔑 Llaves VAPID cargadas desde vapid_keys.json")
else:
    # Generar nueva clave ECDH P-256
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Extraer raw private key (32 bytes) como base64url
    private_numbers = private_key.private_numbers()
    raw_private = private_numbers.private_value.to_bytes(32, byteorder='big')
    private_key_raw_b64 = base64.urlsafe_b64encode(raw_private).decode("utf-8")

    # Crear objeto Vapid desde raw
    vapid_obj = Vapid.from_raw(private_key_raw_b64.encode("utf-8"))

    # Clave pública en formato "uncompressed point" → base64url
    raw_public = vapid_obj.public_key.public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    public_key_b64 = base64.urlsafe_b64encode(raw_public).decode("utf-8")

    # Guardar para reutilizar
    saved_keys = {
        "publicKey": public_key_b64,
        "privateKeyRaw": private_key_raw_b64,
    }
    with open(KEYS_FILE, "w") as f:
        json.dump(saved_keys, f, indent=2)
    print("🔑 Llaves VAPID generadas y guardadas en vapid_keys.json")

# ─── Almacén de suscripciones (en memoria) ────────────────
suscripciones = []

# ─── Historial de alertas (para polling desde Edge/otros) ──
alertas_historial = []  # últimas N alertas enviadas
MAX_ALERTAS_HISTORIAL = 50

# ─── Endpoints ────────────────────────────────────────────

@app.get("/vapid_public_key")
async def get_vapid_key():
    """Devuelve la clave pública VAPID para el frontend."""
    return {"public_key": public_key_b64}


@app.post("/suscribir")
async def suscribir(request: Request):
    """Guarda la suscripción push de un dispositivo."""
    suscripcion = await request.json()

    # Evitar duplicados
    ya_existe = any(
        s.get("endpoint") == suscripcion.get("endpoint")
        for s in suscripciones
    )

    if not ya_existe:
        suscripciones.append(suscripcion)
        print(f"📱 Nueva suscripción (#{len(suscripciones)})")
    else:
        print("📱 Suscripción ya existente, ignorada")

    return {"ok": True, "total": len(suscripciones)}


@app.post("/desuscribir")
async def desuscribir(request: Request):
    """Elimina todas las suscripciones (para forzar re-suscripción con claves nuevas)."""
    global suscripciones
    total_antes = len(suscripciones)
    suscripciones = []
    print(f"🗑️ Todas las suscripciones eliminadas ({total_antes})")
    return {"ok": True, "eliminadas": total_antes}


@app.post("/enviar_alerta")
async def enviar_alerta(request: Request):
    """Envía una notificación push a todos los dispositivos suscritos."""
    try:
        datos = await request.json()

        if len(suscripciones) == 0:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "No hay dispositivos suscritos. "
                              "Abre la app en el teléfono y suscríbete primero."
                }
            )

        alerta_data = {
            "id": str(uuid.uuid4()),
            "titulo": datos.get("titulo", "🚨 ALERTA DepthGuard"),
            "mensaje": datos.get("mensaje", "Alerta de seguridad detectada"),
            "tipo": datos.get("tipo", "fraude"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Guardar en historial para polling
        alertas_historial.append(alerta_data)
        if len(alertas_historial) > MAX_ALERTAS_HISTORIAL:
            alertas_historial.pop(0)

        payload = json.dumps({
            "titulo": alerta_data["titulo"],
            "mensaje": alerta_data["mensaje"],
            "tipo": alerta_data["tipo"],
        })

        print(f"\n🚨 Enviando push a {len(suscripciones)} dispositivo(s)...")

        enviadas = 0
        fallidas = 0
        expiradas = []
        errores_detalle = []

        for i, sub in enumerate(suscripciones):
            print(f"  📤 Enviando a: {sub.get('endpoint', '???')[:80]}...")
            try:
                # Urgency: high → Edge no filtra la notificación
                # content_encoding: aes128gcm → estándar moderno que Edge espera
                response = webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=vapid_obj,
                    vapid_claims={"sub": "mailto:test@depthguard.local"},
                    ttl=86400,
                    content_encoding="aes128gcm",
                    headers={"Urgency": "high", "Topic": "depthguard-alert"},
                    verbose=True,
                )
                status = getattr(response, 'status_code', None)
                body = getattr(response, 'text', '')
                print(f"  ✅ Enviada (status: {status})")
                enviadas += 1
            except WebPushException as e:
                fallidas += 1
                resp = getattr(e, 'response', None)
                status = resp.status_code if resp is not None else 'N/A'
                body = resp.text[:200] if resp is not None and hasattr(resp, 'text') else str(e)
                print(f"  ❌ WebPush Error (status {status}): {body[:120]}")
                errores_detalle.append(f"status={status}: {body[:100]}")
                if resp is not None and resp.status_code in (404, 410):
                    expiradas.append(i)
                    print("  🗑️ Suscripción expirada removida")
            except Exception as e:
                fallidas += 1
                print(f"  ❌ Error inesperado: {type(e).__name__}: {e}")
                # Remover suscripciones con errores de conexión (endpoint inválido)
                if "permanently-removed" in str(e) or "NameResolution" in str(e):
                    expiradas.append(i)
                    print("  🗑️ Suscripción con endpoint inválido removida")
                errores_detalle.append(str(e)[:100])

        # Remover expiradas (en orden inverso)
        for i in reversed(expiradas):
            suscripciones.pop(i)

        return {
            "enviadas": enviadas,
            "fallidas": fallidas,
            "total": len(suscripciones),
            "errores": errores_detalle,
        }

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error interno: {str(e)}"}
        )


@app.get("/estado")
async def estado():
    """Devuelve el estado del servidor."""
    return {
        "servidor": "activo",
        "suscripciones": len(suscripciones),
        "vapid_configurado": True,
    }


@app.get("/alertas_recientes")
async def alertas_recientes(desde: str = ""):
    """Devuelve alertas más recientes que 'desde' (ISO timestamp).
    
    Usado como fallback de polling para navegadores que no
    soportan Web Push (como Edge Android).
    """
    if not desde:
        # Sin filtro, devolver las últimas 5
        return {"alertas": alertas_historial[-5:]}

    # Filtrar alertas más nuevas que el timestamp dado
    nuevas = [
        a for a in alertas_historial
        if a["timestamp"] > desde
    ]
    return {"alertas": nuevas}



FRONTEND_DIR = Path(__file__).parent.parent / "frontend_pwa" / "public"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")

# ─── Iniciar ─────────────────────────────────────────────
if __name__ == "__main__":
    print("")
    print("╔══════════════════════════════════════════╗")
    print("║   🛡️  DepthGuard - Push Test Server      ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║   Local:  http://localhost:{PORT}          ║")
    print("║   Ahora ejecuta: ngrok http 3000        ║")
    print("╚══════════════════════════════════════════╝")
    print("")

    uvicorn.run(app, host="0.0.0.0", port=PORT)
