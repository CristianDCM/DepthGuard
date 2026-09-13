import subprocess, sys, os
sys.path.insert(0, os.getcwd())
print("=" * 58)
print(" DIAGNOSTICO DEPTHGUARD")
print("=" * 58)

# 1. Version del codigo
try:
    c = subprocess.run(["git","log","--oneline","-1"],capture_output=True,text=True).stdout.strip()
    print(f"\n1) Ultimo commit: {c}")
except Exception as e:
    print(f"\n1) git no disponible: {e}")

import backend.supabase_cliente as sc
tiene_fix = hasattr(sc, "_argumentos_cliente")
print(f"   Arreglo de cabeceras presente: {'SI' if tiene_fix else 'NO  <-- falta git pull'}")

# 2. Que hay en el .env (sin mostrar valores)
from config.settings import (SUPABASE_URL, SUPABASE_EDGE_KEY, SUPABASE_ANON_KEY,
                             SUPABASE_SERVICE_KEY, PERMITIR_SERVICE_KEY, CLEANUP_EN_EDGE)
print("\n2) Variables del .env:")
for n, v in (("SUPABASE_URL", SUPABASE_URL), ("SUPABASE_EDGE_KEY", SUPABASE_EDGE_KEY),
             ("SUPABASE_ANON_KEY", SUPABASE_ANON_KEY), ("SUPABASE_SERVICE_KEY", SUPABASE_SERVICE_KEY)):
    print(f"   {n:22} {'definida (' + str(len(v)) + ' chars)' if v else 'VACIA'}")
print(f"   {'PERMITIR_SERVICE_KEY':22} {PERMITIR_SERVICE_KEY}")
print(f"   {'CLEANUP_EN_EDGE':22} {CLEANUP_EN_EDGE}")

# 3. Que cabeceras se van a enviar de verdad
print("\n3) Cabeceras que se enviaran:")
try:
    import base64, json
    def rol(t):
        t = t.replace("Bearer ", "")
        p = t.split(".")[1]; p += "=" * (-len(p) % 4)
        try: return json.loads(base64.urlsafe_b64decode(p)).get("role","?")
        except Exception: return "NO ES UN JWT"
    cli = sc.obtener_cliente()
    h = {k.lower(): v for k, v in cli.postgrest.session.headers.items()}
    print(f"   modo de clave : {sc.modo_clave}")
    print(f"   apikey        -> rol '{rol(h.get('apikey',''))}'")
    print(f"   Authorization -> rol '{rol(h.get('authorization',''))}'")
    ok = rol(h.get('apikey','')) in ("anon","service_role")
    print(f"\n   {'CORRECTO' if ok else 'MAL: apikey debe ser anon o service_role'}")
except Exception as e:
    print(f"   ERROR: {type(e).__name__}: {e}")
print("=" * 58)
