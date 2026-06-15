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
        print("⚠️ Archivo .env no encontrado. Usando valores por defecto.")
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
SUPABASE_SERVICE_KEY = _env.get("SUPABASE_SERVICE_KEY", "")

# === ANTI-SPOOFING ===
UMBRAL_VARIANZA = float(_env.get("UMBRAL_VARIANZA", "0.7"))
UMBRAL_RANGO_PROF = float(_env.get("UMBRAL_RANGO_PROF", "3.0"))
UMBRAL_SUAVIDAD = float(_env.get("UMBRAL_SUAVIDAD", "5.0"))
RANGO_DIST_MIN = float(_env.get("RANGO_DIST_MIN", "25"))
RANGO_DIST_MAX = float(_env.get("RANGO_DIST_MAX", "150"))
MIN_PIXELES_VALIDOS = float(_env.get("MIN_PIXELES_VALIDOS", "0.30"))

# === RECONOCIMIENTO ===
TOLERANCIA_FACIAL = float(_env.get("TOLERANCIA_FACIAL", "0.55"))
COOLDOWN_EMBEDDING = float(_env.get("COOLDOWN_EMBEDDING", "2.0"))
COOLDOWN_ANTISPOOFING = float(_env.get("COOLDOWN_ANTISPOOFING", "0.3"))
COOLDOWN_EVENTO = float(_env.get("COOLDOWN_EVENTO", "5"))

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
