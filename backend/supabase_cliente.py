"""
Cliente Supabase singleton para el nodo edge.
Usa la service_role key para escribir sin restricciones de RLS.
"""

import os
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_KEY

_cliente: Client | None = None


def obtener_cliente() -> Client:
    """Retorna el cliente Supabase (singleton)."""
    global _cliente

    if _cliente is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "SUPABASE_URL y SUPABASE_SERVICE_KEY deben estar en .env"
            )
        
        # FIX: httpx fails to parse NO_PROXY if it contains '::1' (IPv6 loopback)
        if "NO_PROXY" in os.environ:
            del os.environ["NO_PROXY"]
            
        _cliente = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    return _cliente

