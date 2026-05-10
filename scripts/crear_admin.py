"""Crear cuenta de administrador en Supabase."""
import sys, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.supabase_cliente import obtener_cliente


def _hash_password(password):
    salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + hash_bytes.hex()


supabase = obtener_cliente()
usuario = input("Usuario: ").strip()
password = input("Contraseña: ").strip()

if usuario and password:
    supabase.table("admin").insert({
        "usuario": usuario,
        "password_hash": _hash_password(password),
    }).execute()
    print(f"✅ Admin '{usuario}' creado en Supabase")
else:
    print("❌ Datos vacíos")

