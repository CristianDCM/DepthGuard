# -*- mode: python ; coding: utf-8 -*-
"""
Receta de PyInstaller para DepthGuard (fase 3 de docs/EMPAQUETADO.md).

    pyinstaller empaquetado/DepthGuard.spec --noconfirm

Produce dist/DepthGuard/ (modo onedir): DepthGuard.exe + _internal/. Onedir
y no onefile: onefile descomprime cientos de MB en una carpeta temporal en
cada arranque y lo marcan mas antivirus. El instalador (fase 4) ya le da al
cliente un solo archivo.

Lo que PyInstaller NO encuentra solo, y por que esta aqui:

  - mediapipe: carga sus modelos (.tflite) y grafos (.binarypb) desde la
    carpeta del paquete en tiempo de ejecucion. No hay hook que los copie.
  - face_recognition_models: los .dat de dlib, igual. Sin ellos,
    face_recognition NO lanza un error: llama a quit() y el proceso sale
    con codigo 0.
  - pyrealsense2: sus .pyd/.dll viven dentro del paquete.

Lo que se EXCLUYE a proposito (unos 490 MB): jax, jaxlib y scipy. mediapipe
los declara como dependencia, pero solo los usan su conversor
(mediapipe.tasks.python.genai.converter) y sus tests, nunca Face Mesh. Si
algun dia hicieran falta, la autoprueba del build (`DepthGuard.exe
--autoprueba`) fallaria antes de publicar nada.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

RAIZ = os.path.dirname(SPECPATH)  # noqa: F821 - lo define PyInstaller

# Datos de los tests internos de mediapipe: no se usan.
_MEDIAPIPE_FUERA = ["**/test/**", "**/tests/**", "**/*_test.py"]

datas = (
    collect_data_files("mediapipe", excludes=_MEDIAPIPE_FUERA)
    + collect_data_files("face_recognition_models")
)

binaries = (
    collect_dynamic_libs("mediapipe")
    + collect_dynamic_libs("pyrealsense2")
)

a = Analysis(
    [os.path.join(RAIZ, "iniciar.py")],
    pathex=[RAIZ],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # Importados dentro de funciones o condicionalmente; se declaran
        # para no depender de que el analisis los vea.
        "autoprueba",
        "motor_ia.camara.realsense",
        "motor_ia.camara.simulada",
        "motor_ia.reconocimiento.motor_onnx",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "jax", "jaxlib", "scipy",
        # Solo el conversor: es el que importa jax. El paquete genai en si
        # NO se puede excluir, mediapipe/tasks/python/__init__.py lo importa
        # siempre (excluirlo rompe Face Mesh; lo detecto la autoprueba).
        "mediapipe.tasks.python.genai.converter",
        "tkinter",
        "pytest", "unittest.mock",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DepthGuard",
    debug=False,
    strip=False,
    # UPX comprime DLLs y es una fuente conocida de falsos positivos de
    # antivirus y de DLLs que dejan de cargar. No compensa.
    upx=False,
    # Con consola por ahora: los mensajes de arranque (postura de seguridad,
    # errores) se ven. Si se oculta o no se decide en la fase 5.
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DepthGuard",
)
