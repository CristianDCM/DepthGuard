"""
Heartbeat del nodo edge.

Actualiza `estado_sistema.ultimo_heartbeat` cada 30 segundos
para que el frontend sepa si el edge está online.

También reporta las cámaras activas y su tipo para que el
dashboard muestre información consistente.

Al apagar el edge, se llama `apagar_camaras()` para marcar
todo como inactivo inmediatamente en Supabase.
"""

import time
import datetime

from backend.supabase_cliente import obtener_cliente


# Definición de las 2 cámaras del sistema (arquitectura multicámara)
# El heartbeat solo marca como activa la que realmente está corriendo.
_CAMARAS_SISTEMA = [
    {
        "camera_id": "entrada_principal",
        "camera_type": "3D",
        "activa": False,
        "modelo": "Intel RealSense D435",
    },
    {
        "camera_id": "entrada_secundaria",
        "camera_type": "2D",
        "activa": False,
        "modelo": "Webcam IP",
    },
]


def _construir_camaras(camera_id_activa: str, camera_type: str,
                       modo_camara: str) -> list:
    """Construye el array de cámaras marcando la activa correctamente."""
    camaras = []
    for cam in _CAMARAS_SISTEMA:
        if cam["camera_id"] == camera_id_activa:
            camaras.append({
                **cam,
                "camera_type": camera_type,
                "activa": True,
                "modelo": "Intel RealSense" if modo_camara == "realsense" else "Webcam Simulada",
            })
        else:
            camaras.append({**cam, "activa": False})
    return camaras


def iniciar_heartbeat(intervalo: int = 30, camera_id: str = "entrada_principal",
                      camera_type: str = "2D", modo_camara: str = "simulada"):
    """
    Bucle infinito que actualiza el heartbeat en Supabase.
    Ejecutar en un hilo daemon.

    camera_id: identificador de la cámara activa.
    camera_type: tipo de verificación ("3D" o "2D").
    modo_camara: modo de la cámara ("simulada" o "realsense").
    """
    supabase = obtener_cliente()
    print(f"[Heartbeat] Activo (cada {intervalo}s)")

    # Construir info de cámaras: solo la activa se marca True
    camaras = _construir_camaras(camera_id, camera_type, modo_camara)

    while True:
        try:
            ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
            supabase.table("estado_sistema").update({
                "ultimo_heartbeat": ahora,
                "camara_activa": True,
                "modo_camara": modo_camara,
                "camaras": camaras,
                "updated_at": ahora,
            }).eq("id", 1).execute()
        except Exception as e:
            print(f"[Heartbeat] Error: {e}")

        time.sleep(intervalo)


def apagar_camaras():
    """
    Marca todas las cámaras como inactivas en Supabase.
    Llamar al hacer shutdown del edge (Ctrl+C / exit).
    """
    try:
        supabase = obtener_cliente()
        ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Todas las cámaras inactivas
        camaras_off = [{**cam, "activa": False} for cam in _CAMARAS_SISTEMA]

        supabase.table("estado_sistema").update({
            "camara_activa": False,
            "camaras": camaras_off,
            "updated_at": ahora,
        }).eq("id", 1).execute()

        print("[Heartbeat] Cámaras marcadas como inactivas en Supabase")
    except Exception as e:
        print(f"[Heartbeat] Error al apagar cámaras: {e}")
