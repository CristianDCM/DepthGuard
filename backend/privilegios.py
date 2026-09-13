"""
Inventario de privilegios del nodo edge.

Esto es la ESPECIFICACION de minimo privilegio: cada operacion que el edge
ejecuta de verdad contra Supabase, sacada de auditar el codigo (no de
suponer). El fichero supabase/rls_edge.sql implementa exactamente esta lista.

Por que existe como codigo y no como comentario: tests/test_privilegios.py
escanea el repositorio buscando llamadas `.table(...)` y `.storage.from_(...)`
y falla si encuentra alguna que no este declarada aqui. Asi, anadir una
operacion privilegiada nueva obliga a pasar por este fichero, y de ahi a
revisar las politicas RLS. Sin ese guardarrail, la RLS se queda atras en
silencio y el edge acaba necesitando mas permisos de los que deberia.

CONTEXTO DE SEGURIDAD
---------------------
El edge usaba la service_role key, que salta TODA la RLS por diseno. Quien
leyera el .env de la maquina (acceso fisico, USB, malware, un backup) obtenia
control total del proyecto: todos los usuarios, TODAS LAS PLANTILLAS
BIOMETRICAS, todo el historico, y escritura sin restriccion. Nada de lo que
hay en esta lista necesita ese nivel.
"""

from collections import namedtuple

Privilegio = namedtuple("Privilegio", ["recurso", "operaciones", "usado_en", "nota"])


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------

TABLAS = [
    Privilegio(
        recurso="usuarios",
        operaciones=("select",),
        usado_en="motor_ia/pipeline.py:_cargar_usuarios_supabase, "
                 "backend/command_listener.py:_cargar_usuario_objetivo",
        nota="Solo id, nombre, embeddings_json, num_angulos, activo; y solo "
             "filas con activo = true. El command listener lo lee ademas para "
             "verificar contra la BD a quien va a enrolar un comando, en vez "
             "de fiarse de lo que diga el comando.",
    ),
    Privilegio(
        recurso="usuarios",
        operaciones=("update",),
        usado_en="backend/command_listener.py:_ejecutar_registro",
        nota="Solo embeddings_json y num_angulos, al completar un registro. "
             "El comando se autoriza antes de llegar aqui "
             "(backend/autorizacion_registro.py): el usuario debe existir y "
             "estar activo, el nombre debe cuadrar con la BD, y sobrescribir "
             "biometria existente exige autorizacion explicita.",
    ),
    Privilegio(
        recurso="historial",
        operaciones=("insert",),
        usado_en="backend/supabase_sync.py",
        nota="Eventos de acceso, desconocido y fraude.",
    ),
    Privilegio(
        recurso="historial",
        operaciones=("select", "delete"),
        usado_en="backend/cleanup.py",
        nota="Retencion de datos. NO deberia ser un privilegio del "
             "dispositivo: un edge comprometido puede borrar el rastro de "
             "auditoria. Mover a pg_cron en la base de datos y poner "
             "CLEANUP_EN_EDGE=false (ver supabase/rls_edge.sql).",
    ),
    Privilegio(
        recurso="estado_sistema",
        operaciones=("select", "update"),
        usado_en="backend/heartbeat.py",
        nota="Solo la fila id = 1, y solo las columnas de heartbeat y estado "
             "de camaras.",
    ),
    Privilegio(
        recurso="comandos_edge",
        operaciones=("select", "update"),
        usado_en="backend/command_listener.py",
        nota="Lee comandos pendientes y actualiza su estado/progreso. "
             "El edge NUNCA necesita insertar ni borrar comandos.",
    ),
]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

STORAGE = [
    Privilegio(
        recurso="capturas",
        operaciones=("upload",),
        usado_en="backend/supabase_sync.py, backend/snapshot_uploader.py",
        nota="Fotos de eventos y el frame de preview en vivo. El bucket es "
             "PUBLICO a dia de hoy (hallazgo C5, pendiente): son imagenes "
             "faciales de personas identificadas en URLs sin caducidad.",
    ),
    Privilegio(
        recurso="capturas",
        operaciones=("remove",),
        usado_en="backend/cleanup.py",
        nota="Mismo caso que el delete de historial: deberia hacerlo la base "
             "de datos, no el dispositivo.",
    ),
]


# Tablas que el edge NO debe poder tocar de ninguna forma. Si alguna vez
# aparece una llamada a una de estas, es un fallo de diseno, no un permiso
# que anadir.
TABLAS_PROHIBIDAS = frozenset({
    "admin",                  # no existe (la auth es Supabase Auth); se deja
                              # por si alguien la crea alguna vez
    "suscripciones_push",     # endpoints de notificacion de los usuarios
    "notificacion_cooldown",  # estado interno del envio de notificaciones
})


def tablas_permitidas():
    """Conjunto de tablas que el edge puede tocar."""
    return {p.recurso for p in TABLAS}


def buckets_permitidos():
    """Conjunto de buckets de Storage que el edge puede tocar."""
    return {p.recurso for p in STORAGE}


def resumen():
    """Texto legible del inventario, para diagnostico."""
    lineas = ["Privilegios del edge (minimo necesario):"]
    for p in TABLAS:
        lineas.append(f"  tabla   {p.recurso:16} {'/'.join(p.operaciones)}")
    for p in STORAGE:
        lineas.append(f"  storage {p.recurso:16} {'/'.join(p.operaciones)}")
    lineas.append(f"  prohibidas: {', '.join(sorted(TABLAS_PROHIBIDAS))}")
    return "\n".join(lineas)
