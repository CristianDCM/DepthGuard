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

from supabase import create_client, Client, ClientOptions

from config.settings import SUPABASE_URL, SUPABASE_ANON_KEY
from backend.claves import (
    elegir_clave, clave_realtime, texto_aviso, EDGE, ClaveAusenteError,
)

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

        _cliente = create_client(*_argumentos_cliente(clave, modo_clave))

    return _cliente


def _argumentos_cliente(clave, modo):
    """
    Monta (url, apikey, options) segun el tipo de clave.

    Supabase usa DOS cabeceras distintas y no son intercambiables:

      apikey          -> la mira la puerta de entrada del proyecto, y SOLO
                         acepta la clave anon o la service_role.
      Authorization   -> la mira PostgREST para decidir con que rol de
                         Postgres ejecuta la consulta. Acepta cualquier JWT
                         valido del proyecto.

    Con la clave de dispositivo hay que separarlas: la anon en `apikey` para
    pasar la puerta, y el token del edge en `Authorization` para que PostgREST
    cambie al rol depthguard_edge. Ponerlo en las dos, que es lo que hacia
    antes create_client(url, clave), devuelve 401 "Invalid API key" con la
    pista literal "Double check your Supabase `anon` or `service_role` API
    key" — la puerta rechaza el token del edge porque no es ninguna de esas
    dos, sin llegar a mirar la firma.

    Con service_role no hace falta separarlas: esa clave si vale como apikey.
    """
    if modo != EDGE:
        return SUPABASE_URL, clave, None

    if not SUPABASE_ANON_KEY:
        raise ClaveAusenteError(
            "Con SUPABASE_EDGE_KEY hace falta tambien SUPABASE_ANON_KEY.\n"
            "   La puerta de entrada de Supabase solo acepta la clave anon o "
            "la service_role\n"
            "   en la cabecera apikey; el token del edge va aparte, en "
            "Authorization."
        )

    return (
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        ClientOptions(headers={"Authorization": f"Bearer {clave}"}),
    )


def clave_sin_privilegios() -> str:
    """Clave para la senalizacion WebRTC (ver backend/claves.py)."""
    return clave_realtime()


def modo_clave_actual():
    """
    Con que clave se esta operando: "edge", "service_role" o
    "sin_configurar". Es una funcion y no la variable, porque el modo se fija
    al crear el cliente; importar la variable la congelaria en su valor
    inicial.
    """
    return modo_clave


def avisar_si_clave_insegura():
    """
    Aviso suelto de service_role. El arranque usa el informe de postura
    (backend/postura_seguridad.py), que cubre esto y el resto; esto queda
    para usos puntuales.
    """
    aviso = texto_aviso(modo_clave)
    if aviso:
        print(aviso)
