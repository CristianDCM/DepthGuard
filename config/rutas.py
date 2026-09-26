"""
Donde vive cada cosa en disco, con y sin empaquetar.

Sin empaquetar (python iniciar.py) todo sigue exactamente donde estaba: en la
raiz del repo. Este modulo existe para el caso empaquetado (PyInstaller), en el
que esa suposicion se rompe de dos maneras:

  1. __file__ ya no apunta al repo sino a una carpeta interna del ejecutable.
     Buscar ahi el .env es no encontrarlo nunca.
  2. El programa se instala en "Program Files", que un usuario normal NO puede
     escribir. Guardar ahi capturas o el .env falla en cuanto el equipo no
     arranca como administrador, o sea, en produccion.

Por eso se separan dos carpetas:

  - DIR_RECURSOS: lo que viene DENTRO del programa (solo lectura).
  - DIR_DATOS:    lo que el programa escribe o el instalador configura
                  (.env, capturas, modelos descargados). Empaquetado va a
                  %PROGRAMDATA%\\DepthGuard, que es escribible y comun a todos
                  los usuarios del equipo (tambien a una tarea programada o a
                  un servicio, que no corren con el perfil del usuario).

DEPTHGUARD_DATOS permite forzar la carpeta de datos en cualquier modo, para
pruebas o para instalaciones con varias copias en el mismo equipo.
"""

import os
import sys

_RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOMBRE_APP = "DepthGuard"


def resolver(empaquetado, dir_interno, entorno, raiz_repo):
    """
    Calcula (DIR_RECURSOS, DIR_DATOS) sin tocar el estado global, para que se
    pueda probar el caso empaquetado desde un test normal.

    empaquetado: sys.frozen (True dentro de un ejecutable de PyInstaller).
    dir_interno: sys._MEIPASS, la carpeta de recursos del ejecutable.
    entorno:     os.environ o un diccionario equivalente.
    raiz_repo:   la raiz del repo, usada cuando NO esta empaquetado.
    """
    if not empaquetado:
        recursos = raiz_repo
        datos = raiz_repo
    else:
        recursos = dir_interno or raiz_repo
        base = entorno.get("PROGRAMDATA") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
        datos = os.path.join(base, NOMBRE_APP)

    forzado = entorno.get("DEPTHGUARD_DATOS", "").strip()
    if forzado:
        datos = os.path.abspath(forzado)

    return recursos, datos


EMPAQUETADO = bool(getattr(sys, "frozen", False))

DIR_RECURSOS, DIR_DATOS = resolver(
    EMPAQUETADO, getattr(sys, "_MEIPASS", None), os.environ, _RAIZ_REPO)

RUTA_ENV = os.path.join(DIR_DATOS, ".env")
CAPTURAS_DIR = os.path.join(DIR_DATOS, "capturas")

# Modelo ONNX opcional (MOTOR_EMBEDDING=onnx). Sin empaquetar se mantiene la
# ruta de siempre, que es donde lo deja scripts/descargar_modelo.py.
if EMPAQUETADO:
    DIR_MODELOS = os.path.join(DIR_DATOS, "modelos")
else:
    DIR_MODELOS = os.path.join(_RAIZ_REPO, "scripts", "_modelos")
