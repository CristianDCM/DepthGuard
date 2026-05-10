"""
Sincronización Edge → Supabase Cloud.

Lee eventos de la cola del Pipeline IA e inserta en Supabase.
Implementa Store-and-Forward: si Supabase no responde, los eventos
se acumulan en un buffer local y se reintentan automáticamente.

Las fotos de eventos se suben a Supabase Storage (bucket "capturas")
y se reemplazan las rutas locales por URLs públicas accesibles desde
el frontend en Vercel.
"""

import os
import queue
import time
import datetime
import threading
import collections

from backend.supabase_cliente import obtener_cliente
from config.settings import CAPTURAS_DIR

# Buffer local para store-and-forward (tolerancia a cortes de internet)
_buffer_pendientes = collections.deque(maxlen=500)
_lock_buffer = threading.Lock()

# Intervalo entre reintentos del buffer (segundos)
_REINTENTO_INTERVALO = 10

# Nombre del bucket en Supabase Storage
_STORAGE_BUCKET = "capturas"


def iniciar_sync(cola_eventos: queue.Queue, camera_id: str = "entrada_principal",
                 camera_type: str = "3D"):
    """
    Hilo principal de sincronización.
    Lee la cola del pipeline IA y envía a Supabase.
    """
    supabase = obtener_cliente()
    print(f"[Sync] Supabase activo (camara: {camera_id} / {camera_type})")

    # Hilo secundario para reintentar eventos fallidos
    hilo_reintento = threading.Thread(
        target=_reintento_loop,
        daemon=True
    )
    hilo_reintento.start()

    while True:
        try:
            evento = cola_eventos.get(timeout=1)
        except queue.Empty:
            continue

        registro = _evento_a_registro(evento, camera_id, camera_type)
        if registro:
            _subir_foto_si_existe(supabase, registro)
            _enviar_a_supabase(supabase, registro)


def _evento_a_registro(evento: dict, camera_id: str,
                       camera_type: str) -> dict | None:
    """Convierte un evento del pipeline al formato de la tabla historial."""
    tipo = evento.get("tipo")

    if tipo == "FRAUDE":
        return {
            "estado": "FRAUDE",
            "nombre": None,
            "usuario_id": None,
            "confianza": None,
            "foto_url": evento.get("foto_ruta"),
            "motivo": evento.get("motivo", "Superficie plana detectada"),
            "metricas_json": evento.get("metricas", {}),
            "camera_id": camera_id,
            "camera_type": camera_type,
            "verification_level": "3D_antispoofing" if camera_type == "3D" else "2D_recognition",
        }

    elif tipo == "ACCESO_PERMITIDO":
        return {
            "estado": "ACCESO_PERMITIDO",
            "nombre": evento.get("nombre"),
            "usuario_id": evento.get("usuario_id"),
            "confianza": evento.get("confianza"),
            "foto_url": evento.get("foto_ruta"),
            "motivo": None,
            "metricas_json": evento.get("metricas", {}),
            "camera_id": camera_id,
            "camera_type": camera_type,
            "verification_level": "3D_antispoofing" if camera_type == "3D" else "2D_recognition",
        }

    elif tipo == "DESCONOCIDO":
        return {
            "estado": "DESCONOCIDO",
            "nombre": None,
            "usuario_id": None,
            "confianza": None,
            "foto_url": evento.get("foto_ruta"),
            "motivo": None,
            "metricas_json": evento.get("metricas", {}),
            "camera_id": camera_id,
            "camera_type": camera_type,
            "verification_level": "3D_antispoofing" if camera_type == "3D" else "2D_recognition",
        }

    # Otros tipos no se procesan en historial.
    # REGISTRO_EMBEDDING ya no llega aquí — el pipeline acumula
    # embeddings directamente en EstadoRegistro y el command_listener
    # los guarda en la tabla usuarios al completar.
    return None


def _subir_foto_si_existe(supabase, registro: dict):
    """
    Si el registro tiene foto_url con ruta local, sube la imagen
    a Supabase Storage y reemplaza la ruta por la URL pública.
    """
    foto_ruta_local = registro.get("foto_url")
    if not foto_ruta_local or foto_ruta_local.startswith("http"):
        # Ya es URL pública (reintento) o no hay foto
        return

    # La ruta local viene como "/capturas/fraude_20260510_143000.jpg"
    nombre_archivo = os.path.basename(foto_ruta_local)
    ruta_completa = os.path.join(CAPTURAS_DIR, nombre_archivo)

    if not os.path.exists(ruta_completa):
        print(f"[Sync] Foto no encontrada: {ruta_completa}")
        registro["foto_url"] = None
        return

    try:
        with open(ruta_completa, "rb") as f:
            supabase.storage.from_(_STORAGE_BUCKET).upload(
                path=nombre_archivo,
                file=f,
                file_options={"content-type": "image/jpeg"}
            )

        url_publica = supabase.storage.from_(_STORAGE_BUCKET).get_public_url(
            nombre_archivo
        )
        registro["foto_url"] = url_publica
    except Exception as e:
        # Si el archivo ya existe en Storage (reintento con mismo nombre)
        if "Duplicate" in str(e) or "already exists" in str(e):
            url_publica = supabase.storage.from_(_STORAGE_BUCKET).get_public_url(
                nombre_archivo
            )
            registro["foto_url"] = url_publica
        else:
            print(f"[Sync] Error subiendo foto a Storage: {e}")
            # Dejar la ruta local; se reintentará con el buffer


def _enviar_a_supabase(supabase, registro: dict):
    """Inserta un registro en la tabla historial. Si falla, lo guarda en buffer."""
    try:
        supabase.table("historial").insert(registro).execute()
    except Exception as e:
        print(f"[Sync] Error enviando a Supabase: {e}")
        with _lock_buffer:
            _buffer_pendientes.append(registro)
        print(f"   Evento guardado en buffer local ({len(_buffer_pendientes)} pendientes)")


def _reintento_loop():
    """Hilo que reintenta enviar eventos del buffer pendiente."""
    supabase = obtener_cliente()

    while True:
        time.sleep(_REINTENTO_INTERVALO)

        if not _buffer_pendientes:
            continue

        with _lock_buffer:
            # Tomar una copia para no bloquear mientras enviamos
            pendientes = list(_buffer_pendientes)
            _buffer_pendientes.clear()

        enviados = 0
        for registro in pendientes:
            try:
                # Reintentar subir la foto si aún es ruta local
                _subir_foto_si_existe(supabase, registro)
                supabase.table("historial").insert(registro).execute()
                enviados += 1
            except Exception:
                # Devolver al buffer si sigue fallando
                with _lock_buffer:
                    _buffer_pendientes.append(registro)

        if enviados > 0:
            print(f"[Sync] Reintento: {enviados}/{len(pendientes)} eventos enviados a Supabase")
