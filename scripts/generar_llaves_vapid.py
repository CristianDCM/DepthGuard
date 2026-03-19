"""Genera llaves VAPID para push notifications."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_vapid import Vapid
import base64
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat
)

vapid = Vapid()
vapid.generate_keys()
vapid.save_key("private_key.pem")
vapid.save_public_key("public_key.pem")

raw_pub = vapid.public_key.public_bytes(
    encoding=Encoding.X962,
    format=PublicFormat.UncompressedPoint
)
pub_b64 = base64.urlsafe_b64encode(raw_pub).decode().rstrip('=')

print()
print("=" * 55)
print("  Llaves VAPID generadas")
print("=" * 55)
print()
print(f"  VAPID_PUBLIC_KEY={pub_b64}")
print()
print("  Copiar esa línea en el archivo .env")
print("  Archivo private_key.pem guardado")
print("=" * 55)
