"""
Politica de seleccion de clave de Supabase.

Vive separado del cliente porque es una decision de SEGURIDAD, y una decision
de seguridad tiene que poder probarse sin levantar el SDK de Supabase ni tener
red. backend/supabase_cliente.py se limita a aplicar lo que se decide aqui.

Regla: la clave restringida gana siempre. La service_role solo entra si no hay
otra y esta explicitamente permitida, porque SALTA TODA LA RLS por diseno —
quien lea el .env de la maquina obtiene control total del proyecto, incluidas
todas las plantillas biometricas.
"""

from config.settings import (
    SUPABASE_EDGE_KEY, SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_KEY, PERMITIR_SERVICE_KEY,
)

# Modos posibles
EDGE = "edge"                   # clave de dispositivo, acotada por RLS
SERVICE_ROLE = "service_role"   # legado, sin limites


class ClaveInseguraError(RuntimeError):
    """Solo hay service_role y esta prohibida por configuracion."""


class ClaveAusenteError(RuntimeError):
    """No hay ninguna clave configurada."""


def elegir_clave(edge_key=None, service_key=None, permitir_service=None):
    """
    Decide con que clave opera el edge.

    Los parametros existen para poder probar la politica; en produccion se
    toman de config.settings.

    Returns:
        (clave, modo) con modo en {EDGE, SERVICE_ROLE}.

    Raises:
        ClaveInseguraError: solo hay service_role y no esta permitida.
        ClaveAusenteError: no hay ninguna clave.
    """
    edge_key = SUPABASE_EDGE_KEY if edge_key is None else edge_key
    service_key = SUPABASE_SERVICE_KEY if service_key is None else service_key
    permitir_service = (PERMITIR_SERVICE_KEY if permitir_service is None
                        else permitir_service)

    if edge_key:
        # Gana siempre, aunque tambien haya service_role configurada: tener
        # las dos en el .env no debe degradar al modo mas privilegiado.
        return edge_key, EDGE

    if service_key:
        if not permitir_service:
            raise ClaveInseguraError(
                "Solo hay SUPABASE_SERVICE_KEY y PERMITIR_SERVICE_KEY=false.\n"
                "   Esa clave salta toda la RLS: no debe vivir en el "
                "dispositivo.\n"
                "   Genera una clave de dispositivo con supabase/rls_edge.sql "
                "y ponla en SUPABASE_EDGE_KEY."
            )
        return service_key, SERVICE_ROLE

    raise ClaveAusenteError(
        "Falta la clave de Supabase en .env.\n"
        "   Usa SUPABASE_EDGE_KEY (restringida por RLS).\n"
        "   Ver supabase/rls_edge.sql para generarla."
    )


def clave_realtime(anon_key=None, **kwargs):
    """
    Clave para la senalizacion WebRTC.

    Ese canal es Broadcast puro: intercambia SDP e ICE y no lee ni escribe
    ninguna tabla, asi que no hay motivo para darle una clave privilegiada.
    Se prefiere la anon; si no esta configurada se cae a la de datos para no
    romper el streaming, pero conviene definir SUPABASE_ANON_KEY.
    """
    anon_key = SUPABASE_ANON_KEY if anon_key is None else anon_key
    if anon_key:
        return anon_key
    clave, _ = elegir_clave(**kwargs)
    return clave


def texto_aviso(modo):
    """
    Aviso de arranque cuando se opera con service_role. Retorna None si la
    configuracion es correcta.
    """
    if modo != SERVICE_ROLE:
        return None
    return (
        "\n AVISO DE SEGURIDAD: el edge esta usando SUPABASE_SERVICE_KEY.\n"
        "    Esa clave SALTA TODA LA RLS. Quien lea el .env de esta maquina\n"
        "    obtiene control total del proyecto Supabase, incluidas todas\n"
        "    las plantillas biometricas de los usuarios.\n"
        "    Migra a SUPABASE_EDGE_KEY con supabase/rls_edge.sql\n"
        "    y pon PERMITIR_SERVICE_KEY=false.\n"
    )
