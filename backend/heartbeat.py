"""
Heartbeat del nodo edge.

Actualiza `estado_sistema.ultimo_heartbeat` cada 30 segundos
para que el frontend sepa si el edge está online.
"""

import time
import datetime

from backend.supabase_cliente import obtener_cliente


def iniciar_heartbeat(intervalo: int = 30):
    """
    Bucle infinito que actualiza el heartbeat en Supabase.
    Ejecutar en un hilo daemon.
    """
    supabase = obtener_cliente()
    print(f"[Heartbeat] Activo (cada {intervalo}s)")

    while True:
        try:
            supabase.table("estado_sistema").update({
                "ultimo_heartbeat": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
                "camara_activa": True,
                "updated_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }).eq("id", 1).execute()
        except Exception as e:
            print(f"[Heartbeat] Error: {e}")

        time.sleep(intervalo)
