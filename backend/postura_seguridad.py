"""
Informe de postura de seguridad al arrancar.

POR QUE EXISTE
--------------
Los arreglos de la auditoria (C1, C3, C4, C5, C6) traen cada uno su ajuste, y
casi todos vienen desactivados por defecto para no romper instalaciones que
todavia no han migrado. Eso deja un riesgo que no es de codigo sino de
operacion: el repositorio esta arreglado y produccion sigue corriendo con la
configuracion de desarrollo, indefinidamente, porque nadie lee un aviso suelto
entre cien lineas de log.

Este modulo reune todas esas comprobaciones en UN informe, y MODO_PRODUCCION
convierte lo grave en un fallo de arranque. Un sistema que no arranca se
arregla hoy; un aviso se ignora durante meses.

Es logica pura: se puede probar sin red, sin camara y sin Supabase.
"""

from collections import namedtuple

from config.settings import (
    MODO_PRODUCCION, MODO_CAMARA, REQUERIR_CAMARA_3D,
    SUPABASE_ANON_KEY, CLEANUP_EN_EDGE, STORAGE_PRIVADO,
    PERMITIR_REENROLAMIENTO, REGISTRO_HMAC_SECRET,
    WEBRTC_CANAL_PRIVADO,
    valor_bruto,
)

CRITICO = "CRITICO"
ALTO = "ALTO"
MEDIO = "MEDIO"

# Orden de gravedad, para ordenar el informe
_ORDEN = {CRITICO: 0, ALTO: 1, MEDIO: 2}

# Severidades que abortan el arranque en MODO_PRODUCCION
BLOQUEANTES = (CRITICO, ALTO)

Hallazgo = namedtuple("Hallazgo", ["id", "severidad", "titulo", "remedio"])


# Contrasenas que NO pueden considerarse secretas: o estuvieron publicadas en
# el README de este repositorio, o son de las primeras que prueba cualquiera.
CLAVES_CONOCIDAS = frozenset({
    "admin123", "admin", "123456", "12345678", "password",
    "contrasena", "changeme", "depthguard", "1234",
})


def evaluar(modo_clave=None, **kwargs):
    """
    Evalua la configuracion y devuelve la lista de hallazgos abiertos.

    Los parametros permiten probar la funcion; por defecto se leen de
    config.settings.

    Args:
        modo_clave: "edge" o "service_role" (backend/claves.py).
    """
    cfg = {
        "modo_camara": MODO_CAMARA,
        "requerir_3d": REQUERIR_CAMARA_3D,
        "anon_key": SUPABASE_ANON_KEY,
        "cleanup_en_edge": CLEANUP_EN_EDGE,
        "storage_privado": STORAGE_PRIVADO,
        "permitir_reenrolamiento": PERMITIR_REENROLAMIENTO,
        "hmac_secret": REGISTRO_HMAC_SECRET,
        "admin_password": valor_bruto("ADMIN_PASSWORD"),
        "admin_usuario": valor_bruto("ADMIN_USUARIO"),
        "canal_privado": WEBRTC_CANAL_PRIVADO,
    }
    cfg.update(kwargs)

    hallazgos = []

    # --- C6: credenciales de administrador en el dispositivo ---
    password = (cfg["admin_password"] or "").strip()
    if password and password.lower() in CLAVES_CONOCIDAS:
        hallazgos.append(Hallazgo(
            "C6", CRITICO,
            "El .env tiene una contrasena de administrador CONOCIDA",
            "Esa contrasena estuvo publicada en el README de este repositorio. "
            "Cambiala YA donde se autentiquen los administradores y borra "
            "ADMIN_PASSWORD del .env del edge.",
        ))
    elif password or (cfg["admin_usuario"] or "").strip():
        hallazgos.append(Hallazgo(
            "C6", MEDIO,
            "El .env del edge guarda credenciales de administrador",
            "Borra ADMIN_USUARIO y ADMIN_PASSWORD del .env: el edge es un nodo "
            "de camara y ningun codigo suyo las usa.",
        ))

    # --- C3: clave de Supabase ---
    if modo_clave == "service_role":
        hallazgos.append(Hallazgo(
            "C3", CRITICO,
            "El edge opera con la service_role key",
            "Salta toda la RLS: quien lea este .env controla el proyecto "
            "entero, plantillas biometricas incluidas. Aplica "
            "supabase/rls_edge.sql, pon SUPABASE_EDGE_KEY y "
            "PERMITIR_SERVICE_KEY=false.",
        ))

    if not cfg["anon_key"]:
        hallazgos.append(Hallazgo(
            "C3", MEDIO,
            "La senalizacion WebRTC usa una clave con privilegios",
            "Define SUPABASE_ANON_KEY: ese canal es Broadcast y no necesita "
            "tocar ninguna tabla.",
        ))

    if cfg["cleanup_en_edge"]:
        hallazgos.append(Hallazgo(
            "C3", MEDIO,
            "El dispositivo puede borrar el historial",
            "Un edge comprometido borraria el rastro de auditoria. Programa la "
            "retencion con pg_cron y pon CLEANUP_EN_EDGE=false.",
        ))

    # --- C5: capturas publicas ---
    if not cfg["storage_privado"]:
        hallazgos.append(Hallazgo(
            "C5", ALTO,
            "Las capturas biometricas son publicas",
            "Las fotos de cada acceso y el preview en vivo estan en URLs sin "
            "autenticacion ni caducidad. Aplica la seccion 4 del SQL, haz que "
            "el frontend lea preview_url de estado_sistema, y pon "
            "STORAGE_PRIVADO=true.",
        ))

    # --- C1: prueba de vida ---
    hay_3d = cfg["modo_camara"] == "realsense"
    if not hay_3d and not cfg["requerir_3d"]:
        hallazgos.append(Hallazgo(
            "C1", ALTO,
            "Se conceden accesos sin sensor de profundidad",
            "El liveness 2D (parpadeo) detiene una foto impresa pero NO un "
            "video en bucle. Usa MODO_CAMARA=realsense y pon "
            "REQUERIR_CAMARA_3D=true.",
        ))

    # --- C2: senalizacion WebRTC ---
    if not cfg["canal_privado"]:
        hallazgos.append(Hallazgo(
            "C2", ALTO,
            "El canal de senalizacion WebRTC es publico",
            "El nombre del canal es predecible y el edge responde a cualquier "
            "oferta: quien se suscriba obtiene video en vivo. Aplica "
            "supabase/rls_realtime.sql, pon private:true en el frontend y "
            "activa WEBRTC_CANAL_PRIVADO=true.",
        ))

    # --- C4: autorizacion de enrolamiento ---
    if cfg["permitir_reenrolamiento"]:
        hallazgos.append(Hallazgo(
            "C4", ALTO,
            "El re-enrolamiento esta permitido de forma permanente",
            "Sobrescribir biometria existente es el vector de suplantacion. "
            "Deja PERMITIR_REENROLAMIENTO=false y activalo solo el rato que "
            "dure un re-enrolamiento legitimo.",
        ))

    if not cfg["hmac_secret"]:
        hallazgos.append(Hallazgo(
            "C4", MEDIO,
            "Los comandos de enrolamiento no van firmados",
            "Configura REGISTRO_HMAC_SECRET y firma los comandos en servidor "
            "para que una base de datos comprometida no pueda ordenar "
            "enrolamientos.",
        ))

    hallazgos.sort(key=lambda h: (_ORDEN[h.severidad], h.id))
    return hallazgos


def bloqueantes(hallazgos):
    """Hallazgos que abortan el arranque en MODO_PRODUCCION."""
    return [h for h in hallazgos if h.severidad in BLOQUEANTES]


def informe(hallazgos, modo_produccion=None):
    """Texto del informe. Retorna None si no hay nada que decir."""
    if modo_produccion is None:
        modo_produccion = MODO_PRODUCCION

    if not hallazgos:
        return (
            "\n" + "=" * 62 + "\n"
            " POSTURA DE SEGURIDAD: sin hallazgos abiertos\n"
            + "=" * 62
        )

    lineas = ["", "=" * 62, " POSTURA DE SEGURIDAD", "=" * 62]

    for h in hallazgos:
        lineas.append(f"\n [{h.severidad}] ({h.id}) {h.titulo}")
        lineas.append(f"     -> {h.remedio}")

    n_bloq = len(bloqueantes(hallazgos))
    lineas.append("")
    lineas.append("-" * 62)
    if modo_produccion:
        lineas.append(f" MODO_PRODUCCION=true y hay {n_bloq} hallazgo(s) "
                      f"bloqueante(s): no se arranca.")
    else:
        lineas.append(f" {len(hallazgos)} hallazgo(s). Con MODO_PRODUCCION=true, "
                      f"{n_bloq} impedirian el arranque.")
    lineas.append("=" * 62)
    return "\n".join(lineas)


def verificar(modo_clave=None, modo_produccion=None, **kwargs):
    """
    Evalua, imprime el informe y decide si se puede arrancar.

    Returns:
        (puede_arrancar, hallazgos)
    """
    if modo_produccion is None:
        modo_produccion = MODO_PRODUCCION

    hallazgos = evaluar(modo_clave=modo_clave, **kwargs)
    print(informe(hallazgos, modo_produccion))

    if modo_produccion and bloqueantes(hallazgos):
        return False, hallazgos
    return True, hallazgos
