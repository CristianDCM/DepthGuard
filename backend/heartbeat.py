"""
Heartbeat del nodo edge.

Actualiza `estado_sistema.ultimo_heartbeat` cada 30 segundos
para que el frontend sepa si el edge está online.

También reporta las cámaras activas y su tipo para que el
dashboard muestre información consistente.
"""

import time
import datetime
import json

from backend.supabase_cliente import obtener_cliente


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

    # Construir info de cámaras para reportar al frontend
    camaras = [
        {
            "camera_id": camera_id,
            "camera_type": camera_type,
            "activa": True,
            "modelo": "Intel RealSense" if modo_camara == "realsense" else "Webcam Simulada",
        }
    ]

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
