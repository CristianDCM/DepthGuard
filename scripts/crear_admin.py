"""Crear cuenta de administrador."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.base_datos import BaseDatos

db = BaseDatos()
usuario = input("Usuario: ").strip()
password = input("Contraseña: ").strip()

if usuario and password:
    db.crear_admin(usuario, password)
    print(f"✅ Admin '{usuario}' creado")
else:
    print("❌ Datos vacíos")
