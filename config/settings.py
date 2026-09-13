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

# Resolucion NATIVA que se le pide a la webcam (modo simulada).
#
# No es la resolucion a la que se detecta ni a la que se transmite: el
# pipeline reduce cada frame a ANCHO_DETECCION (640) para detectar, dibujar
# el preview y enviarlo por WebRTC. El frame nativo solo lo usa el recorte
# del que sale el embedding, y nunca sale de la RAM.
#
# El valor por defecto es 1280x960 a proposito, no 1280x720: es exactamente
# 2x 640x480, asi que el frame reducido queda identico al de antes (mismo
# encuadre, mismo campo de vision) y los umbrales de calidad y de liveness,
# que se evaluan sobre ese frame reducido, siguen significando lo mismo.
# Lo unico que cambia es que el embedding recibe pixeles reales en vez de
# un recorte pequeno interpolado por dlib hasta su chip de 150x150.
#
# Con 16:9 (1280x720) se pierde campo vertical y las caras quedan mas
# pequenas en el frame de deteccion: es una alternativa valida si la camara
# no ofrece 4:3, pero obliga a revisar los umbrales de validacion_calidad.
CAMARA_ANCHO = int(_env.get("CAMARA_ANCHO", "1280"))
CAMARA_ALTO = int(_env.get("CAMARA_ALTO", "960"))

# FPS que se le piden a la camara. El pipeline se limita aparte a TARGET_FPS;
# este valor es el que se negocia con el driver, y sirve sobre todo para
# detectar que la camara NO concedio lo pedido (ver camara/simulada.py).
CAMARA_FPS = int(_env.get("CAMARA_FPS", "30"))

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
#
# El defecto es false porque con la clave restringida el edge NO PUEDE hacer
# la limpieza: no tiene ni permiso de LECTURA sobre historial, asi que la
# consulta que busca los registros caducados falla con 42501 antes de llegar
# a borrar nada. Dejarlo en true solo producia un error cada 24 horas.
# Ponerlo en true tiene sentido unicamente con SUPABASE_SERVICE_KEY, que
# salta toda la RLS y no deberia estar en el .env de un dispositivo.
CLEANUP_EN_EDGE = _env.get("CLEANUP_EN_EDGE", "false").lower() == "true"

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
# === MOTOR DE EMBEDDINGS ===
#
# "dlib" = face_recognition, 128 dimensiones. Lo historico.
# "onnx" = MobileFaceNet entrenado con ArcFace, 512 dimensiones.
#
# Medido en el equipo del edge (16 nucleos, Windows):
#     dlib            217.5 ms por rostro
#     onnx  1 hilo      9.7 ms      22x
#     onnx 16 hilos     3.2 ms      69x
# Y onnx acepta lote: 5 rostros del mismo frame en 26 ms, contra ~1090 ms de
# dlib uno detras de otro. Gasta ademas menos memoria (+32 MB de sesion frente
# a +92 MB de los modelos de dlib).
#
# El defecto sigue siendo dlib A PROPOSITO: los embeddings de los dos motores
# NO son compatibles (128D contra 512D, y otra geometria de alineacion), asi
# que cambiar obliga a volver a registrar a TODOS los usuarios. Cambiarlo por
# sorpresa dejaria el sistema sin reconocer a nadie.
#
# Para cambiar:
#   1. python scripts/descargar_modelo.py
#   2. MOTOR_EMBEDDING=onnx en .env
#   3. volver a registrar a los usuarios
#   4. python scripts/calibrar_umbral.py  (ajustar TOLERANCIA_FACIAL_ONNX)
MOTOR_EMBEDDING = _env.get("MOTOR_EMBEDDING", "dlib").strip().lower()

# Un valor mal escrito ("ONNX2", "arcface") caeria en dlib sin decir nada, y
# quien lo escribio creeria estar usando el motor rapido. Mejor avisar: el
# sistema sigue arrancando con dlib, que es seguro, pero se entera.
_MOTORES = ("dlib", "onnx")
if MOTOR_EMBEDDING not in _MOTORES:
    print(f" MOTOR_EMBEDDING='{MOTOR_EMBEDDING}' no es valido "
          f"(opciones: {', '.join(_MOTORES)}).")
    print("    Se usara dlib.")
    MOTOR_EMBEDDING = "dlib"

RUTA_MODELO_ONNX = _env.get(
    "RUTA_MODELO_ONNX",
    # _BASE_DIR y no BASE_DIR: el alias publico se define al final del fichero,
    # despues de esta linea.
    os.path.join(_BASE_DIR, "scripts", "_modelos", "w600k_mbf.onnx")
)

# Hilos internos de onnxruntime. 0 = que decida la libreria (usa los nucleos
# disponibles). Ponerlo a 1 deja mas CPU libre para el resto del pipeline a
# cambio de unos milisegundos mas por rostro.
ONNX_HILOS = int(_env.get("ONNX_HILOS", "0"))

# --- Umbrales del motor ONNX ---
#
# Este motor devuelve vectores de norma 1, asi que la distancia euclidea entre
# dos embeddings esta acotada en [0, 2] y se relaciona con la similitud coseno
# por  euclidea = sqrt(2 * (1 - coseno)).  Por eso el matching no cambia: mide
# la misma distancia euclidea, solo con otros umbrales.
#
# 1.095 equivale a exigir coseno >= 0.40. Es una eleccion razonable para
# control de acceso (prioriza no dejar pasar a un desconocido sobre no molestar
# al usuario legitimo), pero NO esta calibrada con rostros reales. Usa
# scripts/calibrar_umbral.py con los usuarios ya registrados y ajustala.
TOLERANCIA_FACIAL_ONNX = float(_env.get("TOLERANCIA_FACIAL_ONNX", "1.095"))
MARGEN_IDENTIDAD_ONNX = float(_env.get("MARGEN_IDENTIDAD_ONNX", "0.10"))
ESCALA_CONFIANZA_ONNX = float(_env.get("ESCALA_CONFIANZA_ONNX", "0.12"))

JITTERS_REGISTRO = int(_env.get("JITTERS_REGISTRO", "3"))
JITTERS_RECONOCIMIENTO = int(_env.get("JITTERS_RECONOCIMIENTO", "1"))

# === AUTORIZACION DE REGISTRO BIOMETRICO (hallazgo C4) ===
#
# Sobrescribir la biometria de alguien que YA la tiene es el vector de
# suplantacion: quien pueda escribir en `comandos_edge` apuntaria al
# usuario_id de un administrador y enrolaria su propia cara. Por eso el
# re-enrolamiento exige autorizacion explicita.
#
# Sin firma HMAC, esta config LOCAL del dispositivo es lo unico que el
# atacante no controla (el flag del comando si lo controla). Dejala en false
# y ponla en true solo el rato que dure un re-enrolamiento legitimo.
PERMITIR_REENROLAMIENTO = _env.get("PERMITIR_REENROLAMIENTO", "false").lower() == "true"

# Secreto compartido para verificar comandos firmados. Vacio = sin firma.
# La firma debe generarse EN SERVIDOR (Edge Function de Supabase o backend de
# administracion), nunca en el navegador: un secreto en una SPA no es secreto.
# Ver backend/autorizacion_registro.py para el formato del mensaje firmado.
REGISTRO_HMAC_SECRET = _env.get("REGISTRO_HMAC_SECRET", "")

# === ADMIN ===
#
# AQUI NO HAY CREDENCIALES DE ADMINISTRADOR, A PROPOSITO.
#
# Habia ADMIN_USUARIO / ADMIN_PASSWORD con los valores por defecto
# admin / admin123. Tres problemas a la vez:
#   1. Esa contrasena estaba publicada en el README de un repositorio publico,
#      asi que no era un valor por defecto: era una credencial conocida.
#   2. Si faltaba el .env, settings.py caia a ella en silencio.
#   3. Ningun codigo del edge las usaba. La autenticacion de administradores
#      vive en el frontend / Supabase, no aqui.
#
# El edge es un nodo de camara: no debe guardar credenciales de admin, igual
# que no debe llevar la service_role key. La tabla `admin` esta en
# TABLAS_PROHIBIDAS (backend/privilegios.py) precisamente por eso.
#
# Si tu .env todavia las tiene, el informe de postura de seguridad del
# arranque te lo dira (backend/postura_seguridad.py).


# === MODO PRODUCCION ===
#
# Con true, cualquier hallazgo CRITICO o ALTO del informe de postura ABORTA el
# arranque en vez de imprimir un aviso que nadie lee. Ponlo en true en el
# despliegue real: es lo que evita que el sistema siga funcionando durante
# meses con la configuracion de desarrollo.
MODO_PRODUCCION = _env.get("MODO_PRODUCCION", "false").lower() == "true"


def valor_bruto(clave, defecto=""):
    """
    Lee una clave del .env tal cual, sin exponer el diccionario entero.
    Lo usa el informe de postura para detectar ajustes que ya no deberian
    estar ahi (por ejemplo ADMIN_PASSWORD).
    """
    return _env.get(clave, defecto)

# === RUTAS ===
BASE_DIR = _BASE_DIR
CAPTURAS_DIR = os.path.join(BASE_DIR, "capturas")

# === SENALIZACION WEBRTC (hallazgo C2) ===
#
# El canal de senalizacion es un Broadcast de Supabase Realtime con nombre
# predecible (webrtc-signaling-entrada_principal). Sin autorizacion, cualquiera
# que se suscriba puede mandar una oferta SDP y recibir video en vivo de la
# camara: el edge respondia a toda oferta que llegara.
#
# true = canal PRIVADO (Realtime Authorization). Supabase comprueba la RLS de
# realtime.messages antes de dejar entrar o publicar en el canal, asi que la
# autorizacion se aplica en el transporte y no depende de que el edge sepa
# distinguir a quien le habla.
#
# Requiere DOS cosas antes de activarlo:
#   1. Aplicar supabase/rls_realtime.sql (politicas del canal).
#   2. En el frontend: supabase.realtime.setAuth() y crear el canal con
#      { config: { private: true } }.
# Sin (2), el panel deja de recibir video.
WEBRTC_CANAL_PRIVADO = _env.get("WEBRTC_CANAL_PRIVADO", "false").lower() == "true"

# Tope de conexiones WebRTC simultaneas. Cada una mantiene su propio
# RTCPeerConnection y su codificador; sin tope, abrir ofertas en bucle agota
# la memoria y la CPU del nodo.
WEBRTC_MAX_CONEXIONES = int(_env.get("WEBRTC_MAX_CONEXIONES", "3"))

# === WEBRTC / TURN (Metered) ===
TURN_URL        = _env.get("TURN_URL", "turn:global.relay.metered.ca:80")
TURN_USERNAME   = _env.get("TURN_USERNAME", "")
TURN_CREDENTIAL = _env.get("TURN_CREDENTIAL", "")

# === ALMACENAMIENTO DE CAPTURAS (hallazgo C5) ===
#
# false = bucket publico con get_public_url (comportamiento heredado): las
# fotos faciales de cada acceso y el preview en vivo quedan en URLs sin
# autenticacion ni caducidad.
#
# true = URLs firmadas que caducan. Requiere DOS cosas antes de activarlo:
#   1. Aplicar supabase/rls_edge.sql (seccion 4) para poner el bucket privado.
#   2. Que el frontend lea la URL del preview de estado_sistema.camaras en
#      lugar de construirla a partir del nombre del fichero.
# Sin (2) el preview en vivo se queda en negro.
STORAGE_PRIVADO = _env.get("STORAGE_PRIVADO", "false").lower() == "true"

# === RETENCIÓN DE DATOS ===
DIAS_RETENCION = int(_env.get("DIAS_RETENCION", "30"))

