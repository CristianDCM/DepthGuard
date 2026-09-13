"""
Configuración centralizada de DepthGuard.
Lee el archivo .env UNA VEZ al iniciar.
"""

import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cargar_env():
    """Lee .env y retorna diccionario."""
    config = {}
    ruta = os.path.join(_BASE_DIR, ".env")

    if not os.path.exists(ruta):
        print(" Archivo .env no encontrado. Usando valores por defecto.")
        print(f"   Esperado en: {ruta}")
        print(f"   Copia .env.example como .env")
        return {}

    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            if "=" in linea:
                clave, valor = linea.split("=", 1)
                config[clave.strip()] = valor.strip()

    return config


_env = _cargar_env()

# === CÁMARA ===
MODO_CAMARA = _env.get("MODO_CAMARA", "simulada")

# === SUPABASE ===
SUPABASE_URL = _env.get("SUPABASE_URL", "")

# Clave de DISPOSITIVO, restringida por RLS. Es la que debe usarse.
# Se genera una sola vez siguiendo supabase/rls_edge.sql y solo puede hacer
# lo que declara backend/privilegios.py.
SUPABASE_EDGE_KEY = _env.get("SUPABASE_EDGE_KEY", "")

# Clave publica (anon). Sin privilegios: sirve para la senalizacion WebRTC,
# que es un canal Broadcast y no necesita tocar ninguna tabla.
SUPABASE_ANON_KEY = _env.get("SUPABASE_ANON_KEY", "")

# LEGADO. La service_role key SALTA TODA LA RLS por diseno: quien lea el .env
# de esta maquina obtiene control total del proyecto, incluidas todas las
# plantillas biometricas. Solo se usa si no hay SUPABASE_EDGE_KEY, y el
# arranque lo avisa. Migra en cuanto puedas (supabase/rls_edge.sql).
SUPABASE_SERVICE_KEY = _env.get("SUPABASE_SERVICE_KEY", "")

# Poner a false para NEGARSE a arrancar con service_role. Es lo correcto en
# despliegue real; el default es true para no romper instalaciones que aun no
# han migrado.
PERMITIR_SERVICE_KEY = _env.get("PERMITIR_SERVICE_KEY", "true").lower() == "true"

# Borrado del historico desde el dispositivo. Un edge comprometido con este
# permiso puede borrar el rastro de auditoria, asi que con clave restringida
# esto debe ser false y la retencion la hace pg_cron en la base de datos
# (ver supabase/rls_edge.sql).
CLEANUP_EN_EDGE = _env.get("CLEANUP_EN_EDGE", "true").lower() == "true"

# === ANTI-SPOOFING ===
UMBRAL_VARIANZA = float(_env.get("UMBRAL_VARIANZA", "0.7"))
UMBRAL_RANGO_PROF = float(_env.get("UMBRAL_RANGO_PROF", "3.0"))
UMBRAL_SUAVIDAD = float(_env.get("UMBRAL_SUAVIDAD", "5.0"))
RANGO_DIST_MIN = float(_env.get("RANGO_DIST_MIN", "25"))
RANGO_DIST_MAX = float(_env.get("RANGO_DIST_MAX", "150"))
MIN_PIXELES_VALIDOS = float(_env.get("MIN_PIXELES_VALIDOS", "0.30"))

# === LIVENESS (prueba de vida 2D) ===
#
# El verificador 3D solo prueba vida si la profundidad viene de un sensor
# real. Estas senales dependen de lo que hay delante de la camara y no
# necesitan hardware extra. Ver motor_ia/antispoofing/liveness.py para sus
# limites (no derrotan un video en bucle).

# Exigir camara con profundidad real para conceder accesos.
# False (por defecto) permite operar con webcam apoyandose en el liveness 2D.
# PONER A true EN DESPLIEGUE REAL: es la unica defensa solida contra
# mascaras y video replay.
REQUERIR_CAMARA_3D = _env.get("REQUERIR_CAMARA_3D", "false").lower() == "true"

# Parpadeos necesarios para dar la prueba de vida por superada.
LIVENESS_PARPADEOS_REQUERIDOS = int(_env.get("LIVENESS_PARPADEOS_REQUERIDOS", "1"))

# Segundos delante de la camara sin un solo parpadeo antes de declararlo
# suplantacion en vez de "aun no".
LIVENESS_TIMEOUT = float(_env.get("LIVENESS_TIMEOUT", "12.0"))

# Umbral de cierre/apertura del ojo como FRACCION de la linea base de esa
# persona (un umbral absoluto fallaria con ojos estrechos). La histeresis
# entre los dos evita contar parpadeos por ruido.
LIVENESS_FACTOR_CIERRE = float(_env.get("LIVENESS_FACTOR_CIERRE", "0.72"))
LIVENESS_FACTOR_APERTURA = float(_env.get("LIVENESS_FACTOR_APERTURA", "0.85"))

# EAR minimo para aceptar una muestra como "ojo abierto" al calibrar.
LIVENESS_EAR_MINIMO = float(_env.get("LIVENESS_EAR_MINIMO", "0.12"))

# Frames de ojo abierto necesarios para fijar la linea base.
LIVENESS_FRAMES_BASE = int(_env.get("LIVENESS_FRAMES_BASE", "12"))

# Duracion valida de un parpadeo, en frames. Un cierre mas largo no es un
# parpadeo (ojos cerrados sostenidos, o una foto con los ojos cerrados).
LIVENESS_PARPADEO_MIN_FRAMES = int(_env.get("LIVENESS_PARPADEO_MIN_FRAMES", "1"))
LIVENESS_PARPADEO_MAX_FRAMES = int(_env.get("LIVENESS_PARPADEO_MAX_FRAMES", "10"))

# Textura (deteccion de pantalla). Por defecto se REGISTRA pero NO BLOQUEA:
# estos umbrales dependen de la camara, la optica y la luz del sitio, y sin
# calibrar generan rechazos de personas legitimas. Recoge metricas reales de
# tu instalacion (salen en las metricas del evento) y solo entonces pon
# LIVENESS_TEXTURA_BLOQUEA=true.
LIVENESS_TEXTURA_BLOQUEA = _env.get("LIVENESS_TEXTURA_BLOQUEA", "false").lower() == "true"
LIVENESS_MOIRE_MAX = float(_env.get("LIVENESS_MOIRE_MAX", "0.35"))
LIVENESS_ESPECULAR_MAX = float(_env.get("LIVENESS_ESPECULAR_MAX", "0.08"))

# === RECONOCIMIENTO ===
TOLERANCIA_FACIAL = float(_env.get("TOLERANCIA_FACIAL", "0.50"))
COOLDOWN_EMBEDDING = float(_env.get("COOLDOWN_EMBEDDING", "2.0"))

# Cadencia de embeddings MIENTRAS la votacion temporal aun no decide.
# Con la cadencia lenta (COOLDOWN_EMBEDDING) reunir VOTOS_REQUERIDOS
# tardaria varios segundos, demasiado para un control de acceso; una vez
# hay veredicto se vuelve a la cadencia lenta, que solo re-confirma.
COOLDOWN_EMBEDDING_VOTACION = float(_env.get("COOLDOWN_EMBEDDING_VOTACION", "0.4"))

# Maximo de embeddings que se generan en un mismo frame.
# El bucle del pipeline es de un solo hilo y un embedding cuesta del orden
# de 50-150 ms segun CPU, asi que sin tope N personas en el frame
# multiplicarian por N el tiempo de frame. Con tope, el coste anadido por
# frame esta acotado y las personas se reparten los turnos entre frames.
MAX_EMBEDDINGS_POR_FRAME = int(_env.get("MAX_EMBEDDINGS_POR_FRAME", "1"))
COOLDOWN_ANTISPOOFING = float(_env.get("COOLDOWN_ANTISPOOFING", "0.3"))
COOLDOWN_EVENTO = int(_env.get("COOLDOWN_EVENTO", "5"))

# Margen minimo de separacion entre la mejor identidad y la segunda mejor
# identidad DISTINTA. Si dos personas distintas quedan igual de cerca del
# rostro consultado, es un empate y se rechaza en vez de adivinar.
# Subirlo = menos falsos positivos, mas "DESCONOCIDO".
MARGEN_IDENTIDAD = float(_env.get("MARGEN_IDENTIDAD", "0.06"))

# Ancho de la sigmoide que convierte distancia -> confianza 0..1.
# A distancia == TOLERANCIA_FACIAL la confianza es exactamente 0.50.
# Mas pequeno = transicion mas abrupta alrededor del umbral.
ESCALA_CONFIANZA = float(_env.get("ESCALA_CONFIANZA", "0.07"))

# Penalizacion aplicada a las plantillas registradas en un angulo distinto
# al de la pose detectada. Es una pista suave, no un filtro: si la pose se
# estima mal, el coste maximo es esta cantidad de distancia.
PENALIZACION_POSE = float(_env.get("PENALIZACION_POSE", "0.02"))

# Rango de pose dentro del cual se intenta reconocer. Fuera de esto el
# rostro esta demasiado girado y el embedding no es fiable.
MAX_YAW_RECONOCIMIENTO = float(_env.get("MAX_YAW_RECONOCIMIENTO", "35"))
MAX_PITCH_RECONOCIMIENTO = float(_env.get("MAX_PITCH_RECONOCIMIENTO", "30"))

# Votacion temporal: identificaciones que se acumulan por persona y
# cuantas deben coincidir antes de emitir un evento.
VOTOS_VENTANA = int(_env.get("VOTOS_VENTANA", "5"))
VOTOS_REQUERIDOS = int(_env.get("VOTOS_REQUERIDOS", "3"))

# num_jitters de dlib al generar embeddings. En registro conviene subirlo
# (promedia varias transformaciones -> plantilla mas estable) porque ocurre
# una sola vez; en reconocimiento se queda en 1 por coste de CPU.
JITTERS_REGISTRO = int(_env.get("JITTERS_REGISTRO", "3"))
JITTERS_RECONOCIMIENTO = int(_env.get("JITTERS_RECONOCIMIENTO", "1"))

# === ADMIN (seed inicial) ===
ADMIN_USUARIO = _env.get("ADMIN_USUARIO", "admin")
ADMIN_PASSWORD = _env.get("ADMIN_PASSWORD", "admin123")

# === RUTAS ===
BASE_DIR = _BASE_DIR
CAPTURAS_DIR = os.path.join(BASE_DIR, "capturas")

# === WEBRTC / TURN (Metered) ===
TURN_URL        = _env.get("TURN_URL", "turn:global.relay.metered.ca:80")
TURN_USERNAME   = _env.get("TURN_USERNAME", "")
TURN_CREDENTIAL = _env.get("TURN_CREDENTIAL", "")

# === RETENCIÓN DE DATOS ===
DIAS_RETENCION = int(_env.get("DIAS_RETENCION", "30"))

