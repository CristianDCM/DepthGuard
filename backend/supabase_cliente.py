"""
Clientes Supabase del nodo edge.

Hay DOS clientes a proposito, con privilegios distintos:

  obtener_cliente()          -> datos (tablas + storage). Usa la clave de
                                dispositivo restringida por RLS.
  clave_sin_privilegios()    -> canal Realtime de senalizacion WebRTC, que es
                                Broadcast puro y no toca ninguna tabla.

Antes todo usaba la service_role key, que SALTA TODA LA RLS por diseno. Quien
leyera el .env de la maquina (acceso fisico, un USB, malware, un backup) tenia
control total del proyecto Supabase: todos los usuarios, todas las plantillas
biometricas, todo el historico y escritura sin restriccion. Ninguna de las
operaciones que el edge necesita —ver backend/privilegios.py— requiere eso.
"""

import os

from supabase import create_client, Client

from config.settings import SUPABASE_URL
from backend.claves import elegir_clave, clave_realtime, texto_aviso

_cliente: Client | None = None

# Que clave se acabo usando, para diagnostico y para los avisos de arranque.
# "edge" = restringida por RLS (correcto). "service_role" = legado sin limites.
modo_clave: str = "sin_configurar"


def obtener_cliente() -> Client:
    """Cliente de datos (tablas + storage). Singleton."""
    global _cliente, modo_clave

    if _cliente is None:
        if not SUPABASE_URL:
            raise RuntimeError("SUPABASE_URL debe estar en .env")

        clave, modo_clave = elegir_clave()

        # FIX: httpx fails to parse NO_PROXY if it contains '::1' (IPv6 loopback)
        if "NO_PROXY" in os.environ:
            del os.environ["NO_PROXY"]

        _cliente = create_client(SUPABASE_URL, clave)

    return _cliente


def clave_sin_privilegios() -> str:
    """Clave para la senalizacion WebRTC (ver backend/claves.py)."""
    return clave_realtime()


def avisar_si_clave_insegura():
    """
    Imprime el aviso de arranque si se opera con service_role.
    Llamar una vez desde iniciar.py, despues de crear el cliente.
    """
    aviso = texto_aviso(modo_clave)
    if aviso:
        print(aviso)
