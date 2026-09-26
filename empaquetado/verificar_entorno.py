"""
Comprueba que el entorno de build es EXACTAMENTE el de requirements-build.txt.

Se ejecuta despues de `pip install --no-deps -r requirements-build.txt` y antes
de empaquetar. Si algo no cuadra, sale con codigo 1 y el build se para ahi, en
vez de producir un ejecutable que falla en casa del cliente.

Comprueba:
  1. La version de Python (3.11, la del equipo donde DepthGuard funciona).
  2. Que cada paquete del lock esta instalado y en su version exacta.
  3. Que hay UN solo OpenCV (dos escriben el mismo cv2.pyd).
  4. `pip check`, tolerando unicamente que face-recognition pida `dlib`
     (lo cubre dlib-bin, que tiene otro nombre de paquete).
  5. Que las librerias criticas se importan de verdad.

Uso:
    python empaquetado/verificar_entorno.py
"""

import importlib
import importlib.metadata
import os
import re
import subprocess
import sys

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "requirements-build.txt")

PYTHON_ESPERADO = (3, 11)

PAQUETES_OPENCV = {
    "opencv-python", "opencv-python-headless",
    "opencv-contrib-python", "opencv-contrib-python-headless",
}

# Lo unico que pip check puede decir sin que sea un error.
_PIP_CHECK_TOLERADO = re.compile(r"^face[-_]recognition \S+ requires dlib\b", re.I)

MODULOS_CRITICOS = (
    "numpy", "cv2", "mediapipe", "dlib", "face_recognition",
    "supabase", "aiortc", "av", "onnxruntime", "pyrealsense2",
)


def normalizar(nombre):
    """Nombre de paquete normalizado (PEP 503): Pillow == pillow, a_b == a-b."""
    return re.sub(r"[-_.]+", "-", nombre).lower()


def leer_lock(lineas):
    """{nombre_normalizado: version} a partir de las lineas 'paquete==version'."""
    esperadas = {}
    for linea in lineas:
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        nombre, _, version = linea.partition("==")
        if not version:
            raise ValueError(f"Linea sin version exacta en el lock: {linea!r}")
        esperadas[normalizar(nombre)] = version.strip()
    return esperadas


def comparar(esperadas, instaladas):
    """Errores de version entre el lock y lo instalado ({nombre: version})."""
    errores = []
    for nombre, version in sorted(esperadas.items()):
        actual = instaladas.get(nombre)
        if actual is None:
            errores.append(f"Falta {nombre}=={version}")
        elif actual != version:
            errores.append(f"{nombre}: instalado {actual}, se esperaba {version}")
    return errores


def errores_opencv(instaladas):
    presentes = sorted(n for n in instaladas if n in PAQUETES_OPENCV)
    if len(presentes) == 1:
        return []
    if not presentes:
        return ["No hay ningun OpenCV instalado"]
    return [f"Hay {len(presentes)} OpenCV instalados ({', '.join(presentes)}); "
            "escriben el mismo cv2 y debe quedar uno solo"]


def filtrar_pip_check(salida):
    """Lineas de `pip check` que SI son un problema."""
    return [l for l in salida.splitlines()
            if l.strip() and not l.startswith("No broken requirements")
            and not _PIP_CHECK_TOLERADO.match(l.strip())]


def errores_importacion(modulos, importar=importlib.import_module):
    """
    Importa cada modulo y devuelve los que fallan.

    SystemExit se captura a proposito: face_recognition, si no encuentra sus
    modelos (por ejemplo con una setuptools sin pkg_resources), NO lanza un
    error: imprime un mensaje y llama a quit(), que sale con codigo 0. Sin
    esto, el verificador terminaria "bien" justo en el caso que debe parar.
    """
    errores = []
    for modulo in modulos:
        try:
            importar(modulo)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            errores.append(
                f"No se puede importar {modulo}: {type(e).__name__}: {e}")
    return errores


def _instaladas():
    return {normalizar(d.metadata["Name"]): d.version
            for d in importlib.metadata.distributions()}


def main():
    errores = []

    if sys.version_info[:2] != PYTHON_ESPERADO:
        errores.append(
            f"Python {sys.version.split()[0]}; se esperaba "
            f"{'.'.join(map(str, PYTHON_ESPERADO))}.x")

    with open(LOCK, encoding="utf-8") as f:
        esperadas = leer_lock(f)
    instaladas = _instaladas()
    errores += comparar(esperadas, instaladas)
    errores += errores_opencv(instaladas)

    check = subprocess.run([sys.executable, "-m", "pip", "check"],
                           capture_output=True, text=True)
    errores += [f"pip check: {l}" for l in filtrar_pip_check(check.stdout)]

    errores += errores_importacion(MODULOS_CRITICOS)

    if errores:
        print(f"ENTORNO NO VALIDO ({len(errores)} problemas):")
        for e in errores:
            print(f"  - {e}")
        return 1

    print(f"Entorno OK: Python {sys.version.split()[0]}, "
          f"{len(esperadas)} paquetes en su version exacta, "
          f"{len(MODULOS_CRITICOS)} modulos criticos importan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
