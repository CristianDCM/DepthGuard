"""Servidor FastAPI con WebSocket y Push."""

import os
import json
import queue
import threading
import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from config.settings import FRONTEND_URL, CAPTURAS_DIR
from backend.modelos import LoginRequest, RegistroRequest
from backend.notificaciones import enviar_push


# WebSockets activos
ws_activos = []


def crear_app(cola_eventos, modo_registro, db):
    """Crea y configura la app FastAPI."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Iniciar procesador de cola
        hilo = threading.Thread(
            target=_procesar_cola,
            args=(cola_eventos, db),
            daemon=True
        )
        hilo.start()
        print("✅ Procesador de eventos activo")
        yield

    app = FastAPI(title="DepthGuard API", lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_URL, "http://localhost:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Archivos estáticos (fotos)
    os.makedirs(CAPTURAS_DIR, exist_ok=True)
    app.mount("/capturas", StaticFiles(directory=CAPTURAS_DIR), name="capturas")

    # === ENDPOINTS ===

    @app.get("/")
    def inicio():
        return {"sistema": "DepthGuard", "estado": "activo"}

    @app.get("/estado")
    def estado():
        return {
            "sistema": "activo",
            "camara_activa": True,
            "usuarios": len(db.obtener_usuarios_lista()),
            "vapid_configurado": bool(os.environ.get("VAPID_PUBLIC_KEY"))
        }

    @app.post("/login")
    def login(datos: LoginRequest):
        admin = db.verificar_admin(datos.usuario, datos.password)
        if not admin:
            raise HTTPException(401, "Credenciales inválidas")
        return {"mensaje": "Login exitoso", "token": "depthguard-token"}

    @app.get("/historial")
    def historial(limite: int = 50):
        return {"historial": db.obtener_historial(limite)}

    @app.get("/usuarios")
    def usuarios():
        return {"usuarios": db.obtener_usuarios_lista()}

    @app.delete("/usuarios/{uid}")
    def eliminar(uid: int):
        db.eliminar_usuario(uid)
        modo_registro["recargar_cache"] = True
        return {"mensaje": "Eliminado"}

    @app.post("/registrar_usuario")
    def registrar(datos: RegistroRequest):
        modo_registro["activo"] = True
        modo_registro["nombre"] = datos.nombre
        modo_registro["embeddings"] = []
        modo_registro["paso"] = 0
        return {"mensaje": f"Registro iniciado para {datos.nombre}"}

    @app.get("/registro_estado")
    def registro_estado():
        if modo_registro.get("completado"):
            resultado = modo_registro.get("resultado", {})
            modo_registro["completado"] = False
            return {"completado": True, "datos": resultado}
        return {
            "completado": False,
            "activo": modo_registro.get("activo", False),
            "paso": modo_registro.get("paso", 0)
        }

    @app.post("/suscribir_push")
    def suscribir(suscripcion: dict):
        db.guardar_suscripcion_push(json.dumps(suscripcion))
        return {"mensaje": "Suscripción guardada"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        ws_activos.append(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_json({"tipo": "pong"})
        except WebSocketDisconnect:
            ws_activos.remove(websocket)

    return app


def _procesar_cola(cola, db):
    """Lee eventos del Motor IA y los distribuye."""
    while True:
        try:
            evento = cola.get(timeout=1)
        except queue.Empty:
            continue

        tipo = evento.get("tipo")
        timestamp = datetime.datetime.now().isoformat()

        if tipo == "FRAUDE":
            db.insertar_historial(
                "FRAUDE", evento.get("motivo", ""),
                evento.get("foto_ruta", ""),
                0, evento.get("metricas", {})
            )
            _notificar_ws({"tipo": "FRAUDE", "timestamp": timestamp,
                          "foto": evento.get("foto_ruta")})
            _enviar_push_todos(db, "🚨 Intento de suplantación detectado")

        elif tipo == "ACCESO_PERMITIDO":
            db.insertar_historial(
                "PERMITIDO", evento["nombre"],
                evento.get("foto_ruta", ""),
                evento["confianza"], evento.get("metricas", {})
            )
            _notificar_ws({"tipo": "ACCESO", "nombre": evento["nombre"],
                          "timestamp": timestamp})

        elif tipo == "DESCONOCIDO":
            db.insertar_historial(
                "DESCONOCIDO", "",
                evento.get("foto_ruta", ""),
                0, evento.get("metricas", {})
            )
            _notificar_ws({"tipo": "DESCONOCIDO", "timestamp": timestamp,
                          "foto": evento.get("foto_ruta")})
            _enviar_push_todos(db, "❓ Persona no registrada en la puerta")


def _notificar_ws(data):
    """Envía a todos los WebSockets."""
    desconectados = []
    for ws in ws_activos:
        try:
            import asyncio
            asyncio.run(ws.send_json(data))
        except Exception:
            desconectados.append(ws)
    for ws in desconectados:
        ws_activos.remove(ws)


def _enviar_push_todos(db, mensaje):
    """Envía push a todos los suscritos."""
    for sub in db.obtener_suscripciones_push():
        enviar_push(sub, mensaje)
