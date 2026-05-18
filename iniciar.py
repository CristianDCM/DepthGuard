"""
DEPTHGUARD - Punto de entrada (Nodo Edge).
Ejecutar: python iniciar.py

Arranca 4 hilos:
  1. Pipeline IA — cámara → detección → anti-spoofing → reconocimiento
  2. Sync Supabase — lee la cola de eventos y los envía a Supabase Cloud
  3. Heartbeat — actualiza estado_sistema.ultimo_heartbeat cada 30s
  4. Command Listener — polling de comandos del frontend (registro, etc.)
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import os
import sys
import queue
import threading
import time

# Fix encoding para consola Windows (cp1252 no soporta emojis)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import CAPTURAS_DIR, MODO_CAMARA, SUPABASE_URL
from motor_ia.pipeline import ejecutar_pipeline
from motor_ia.estado_registro import EstadoRegistro
from backend.supabase_sync import iniciar_sync
from backend.heartbeat import iniciar_heartbeat, apagar_camaras
from backend.command_listener import iniciar_command_listener

os.makedirs(CAPTURAS_DIR, exist_ok=True)

print()
print("=" * 55)
print("  🛡️  DEPTHGUARD — Nodo Edge")
print("  Sistema de Control de Acceso Biométrico 3D")
print("=" * 55)
print()

# Verificar configuración de Supabase
if not SUPABASE_URL:
    print("❌ SUPABASE_URL no configurada en .env")
    print("   Copia .env.example como .env y agrega tus credenciales")
    sys.exit(1)

# Cola de eventos: Pipeline IA → Sync Supabase
cola_eventos = queue.Queue()
modo_registro = EstadoRegistro()

# Determinar tipo de cámara
camera_id = "entrada_principal"
camera_type = "3D" if MODO_CAMARA == "realsense" else "2D"

# Hilo 1: Pipeline IA
hilo_ia = threading.Thread(
    target=ejecutar_pipeline,
    args=(cola_eventos, modo_registro, None),  # db=None, ya no se usa SQLite
    daemon=True
)
hilo_ia.start()

# Hilo 2: Sync Supabase (store-and-forward)
hilo_sync = threading.Thread(
    target=iniciar_sync,
    args=(cola_eventos, camera_id, camera_type),
    daemon=True
)
hilo_sync.start()

# Hilo 3: Heartbeat (con info de cámara para el frontend)
hilo_heartbeat = threading.Thread(
    target=iniciar_heartbeat,
    kwargs={
        "camera_id": camera_id,
        "camera_type": camera_type,
        "modo_camara": MODO_CAMARA,
    },
    daemon=True
)
hilo_heartbeat.start()

# Hilo 4: Command Listener (polling de comandos del frontend)
hilo_commands = threading.Thread(
    target=iniciar_command_listener,
    args=(modo_registro,),
    daemon=True
)
hilo_commands.start()

print()
print(f"📷 Cámara: {MODO_CAMARA} ({camera_id} / {camera_type})")
print(f"☁️  Supabase: {SUPABASE_URL[:40]}...")
print(f"💓 Heartbeat: cada 30s")
print(f"📡 Command Listener: polling cada 2s")
print()
print("Presiona Ctrl+C para detener")
print()

# Mantener el proceso vivo (los hilos son daemon)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n⏹️  Apagando DepthGuard...")
    apagar_camaras()
    print("🛑 DepthGuard detenido")
