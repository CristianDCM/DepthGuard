"""
Genera la credencial del nodo edge (SUPABASE_EDGE_KEY).

QUE HACE ESTO, EN CORTO
-----------------------
El edge necesita una credencial propia, limitada: que pueda leer usuarios y
escribir eventos, y nada mas. Esa credencial es un texto largo (un "token")
firmado con el secreto de tu proyecto Supabase.

Este script lo firma AQUI, en tu ordenador, y solo imprime el token. El
secreto no se guarda, no se envia a ningun sitio y no queda en el historial
del terminal.

NUNCA pongas el secreto del proyecto en el .env del edge ni lo compartas: con
el se puede fabricar un token de administrador total. El token que sale de
aqui, en cambio, esta acotado por la RLS.

USO
---
    python scripts/acunar_token_edge.py

No necesita instalar nada: usa solo la libreria estandar de Python.
"""

import base64
import getpass
import hashlib
import hmac
import json
import sys
import time

# Rol de Postgres cuyos permisos tendra el edge. Lo crea
# supabase/rls_edge.sql, y sus permisos exactos estan en
# backend/privilegios.py
ROL = "depthguard_edge"

# Validez por defecto del token, en dias
DIAS_VALIDEZ = 365


def _b64(datos: bytes) -> bytes:
    """Base64 URL-safe sin relleno, como exige JWT."""
    return base64.urlsafe_b64encode(datos).rstrip(b"=")


def firmar_jwt(payload: dict, secreto: str) -> str:
    """Firma un JWT con HS256, que es lo que espera Supabase."""
    cabecera = {"alg": "HS256", "typ": "JWT"}

    def codificar(obj):
        return _b64(json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    a_firmar = codificar(cabecera) + b"." + codificar(payload)
    firma = hmac.new(secreto.encode("utf-8"), a_firmar, hashlib.sha256).digest()
    return (a_firmar + b"." + _b64(firma)).decode("ascii")


def main():
    print()
    print("=" * 62)
    print(" DepthGuard — credencial del nodo edge")
    print("=" * 62)
    print()
    print(" Necesitas el JWT Secret de tu proyecto Supabase:")
    print("   Settings > API > JWT Settings > JWT Secret")
    print()
    print(" No se vera mientras lo pegas, y no se guarda en ningun sitio.")
    print()

    secreto = getpass.getpass(" Pega aqui el JWT Secret y pulsa Enter: ").strip()

    if not secreto:
        print("\n No has pegado nada. Cancelado.")
        return 1
    if len(secreto) < 20:
        print("\n Eso parece demasiado corto para ser el JWT Secret.")
        print("   Comprueba que copiaste el valor completo. Cancelado.")
        return 1

    ahora = int(time.time())
    token = firmar_jwt({
        "role": ROL,
        "iss": "supabase",
        "iat": ahora,
        "exp": ahora + DIAS_VALIDEZ * 24 * 3600,
    }, secreto)

    print()
    print("=" * 62)
    print(" LISTO. Copia la linea siguiente COMPLETA en tu archivo .env:")
    print("=" * 62)
    print()
    print(f"SUPABASE_EDGE_KEY={token}")
    print()
    print("=" * 62)
    print(f" Caduca en {DIAS_VALIDEZ} dias. Apuntalo para renovarlo entonces.")
    print(" Este token SI puede vivir en el .env del edge; el JWT Secret NO.")
    print("=" * 62)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
