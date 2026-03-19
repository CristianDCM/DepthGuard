"""
DEPTHGUARD - Punto de entrada único.
Ejecutar: python iniciar.py
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import os
import sys
import queue
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import PORT, CAPTURAS_DIR
from backend.base_datos import BaseDatos
from motor_ia.pipeline import ejecutar_pipeline

os.makedirs(CAPTURAS_DIR, exist_ok=True)

print()
print("=" * 55)
print("  🛡️  DEPTHGUARD")
print("  Sistema de Control de Acceso Biométrico 3D")
print("=" * 55)
print()

db = BaseDatos()
print("✅ Base de datos lista")

cola_eventos = queue.Queue()

modo_registro = {
    "activo": False,
    "nombre": "",
    "embeddings": [],
    "paso": 0,
    "completado": False,
    "resultado": {},
    "recargar_cache": False
}

hilo_ia = threading.Thread(
    target=ejecutar_pipeline,
    args=(cola_eventos, modo_registro, db),
    daemon=True
)
hilo_ia.start()

print(f"🌐 Servidor: http://localhost:{PORT}")
print()

import uvicorn
from backend.servidor import crear_app

app = crear_app(cola_eventos, modo_registro, db)
uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
