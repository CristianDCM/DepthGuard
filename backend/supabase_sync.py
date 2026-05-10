"""
Sincronización Edge → Supabase Cloud.

Lee eventos de la cola del Pipeline IA e inserta en Supabase.
Implementa Store-and-Forward: si Supabase no responde, los eventos
se acumulan en un buffer local y se reintentan automáticamente.
"""

import queue
import time
import datetime
import threading
import collections

from backend.supabase_cliente import obtener_cliente

# Buffer local para store-and-forward (tolerancia a cortes de internet)
_buffer_pendientes = collections.deque(maxlen=500)
_lock_buffer = threading.Lock()

# Intervalo entre reintentos del buffer (segundos)
_REINTENTO_INTERVALO = 10


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

    # Tipos no reconocidos (ej: REGISTRO_EMBEDDING) se ignoran aquí
    return None


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
                supabase.table("historial").insert(registro).execute()
                enviados += 1
            except Exception:
                # Devolver al buffer si sigue fallando
                with _lock_buffer:
                    _buffer_pendientes.append(registro)

        if enviados > 0:
            print(f"[Sync] Reintento: {enviados}/{len(pendientes)} eventos enviados a Supabase")
