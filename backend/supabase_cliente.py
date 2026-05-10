"""
Cliente Supabase singleton para el nodo edge.
Usa la service_role key para escribir sin restricciones de RLS.
"""

from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_KEY

_cliente: Client | None = None


def obtener_cliente() -> Client:
    """Retorna el cliente Supabase (singleton)."""
    global _cliente

    if _cliente is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "❌ SUPABASE_URL y SUPABASE_SERVICE_KEY deben estar en .env"
            )
        _cliente = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    return _cliente
