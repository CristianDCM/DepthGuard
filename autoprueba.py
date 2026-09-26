"""
Autoprueba del ejecutable: `DepthGuard.exe --autoprueba` (o
`python iniciar.py --autoprueba`).

Carga cada libreria nativa y cada modelo que usa DepthGuard, los hace
trabajar una vez sobre datos sinteticos y sale con codigo 0 si todo funciona
o 1 si algo falla. No abre la camara, no lee el .env y no conecta con Supabase,
asi que corre igual en el build de GitHub que en el equipo del cliente.

Existe porque los fallos tipicos de un ejecutable empaquetado no se ven al
arrancar, sino al usar la pieza que falta: un modelo de mediapipe que no se
copio, una DLL de dlib, un codec de video. Y alguno es silencioso a proposito:
si aiortc no se importa, backend/webrtc_server.py desactiva WebRTC con un aviso
y el sistema sigue funcionando sin video en vivo. Aqui eso cuenta como fallo.
"""

import os
import sys
import time
import uuid

import numpy as np


def _carpeta_datos():
    from config import rutas
    os.makedirs(rutas.DIR_DATOS, exist_ok=True)
    prueba = os.path.join(rutas.DIR_DATOS, f".autoprueba-{uuid.uuid4().hex}")
    with open(prueba, "w", encoding="utf-8") as f:
        f.write("ok")
    os.remove(prueba)
    modo = "empaquetado" if rutas.EMPAQUETADO else "sin empaquetar"
    return f"{modo}, datos en {rutas.DIR_DATOS} (escribible)"


def _opencv():
    import cv2
    imagen = np.full((120, 160, 3), 127, dtype=np.uint8)
    ok, jpg = cv2.imencode(".jpg", imagen)
    if not ok or len(jpg) == 0:
        raise RuntimeError("cv2.imencode no produjo un JPEG")
    lab = cv2.cvtColor(imagen, cv2.COLOR_RGB2LAB)
    cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return f"OpenCV {cv2.__version__}, JPEG y CLAHE"


def _mediapipe():
    from motor_ia.deteccion.face_mesh import DetectorFaceMesh
    detector = DetectorFaceMesh()
    try:
        rostros = detector.detectar(np.zeros((480, 640, 3), dtype=np.uint8))
    finally:
        detector.cerrar()
    if rostros:
        raise RuntimeError("detecto rostros en una imagen negra")
    return "Face Mesh cargo sus modelos y proceso un frame"


def _dlib():
    # La misma llamada que ReconocedorFacial.generar_embedding con el motor
    # dlib, sin depender de MOTOR_EMBEDDING del .env.
    import face_recognition
    from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial
    ReconocedorFacial()
    imagen = np.full((200, 200, 3), 127, dtype=np.uint8)
    vectores = face_recognition.face_encodings(
        imagen, [(40, 160, 160, 40)], num_jitters=1, model="large")
    if len(vectores) != 1 or len(vectores[0]) != 128:
        raise RuntimeError("no se genero un embedding de 128 dimensiones")
    return "modelos de dlib cargados, embedding de 128 dimensiones"


def _webrtc():
    import fractions
    import av
    from aiortc.codecs import H264Encoder, Vp8Encoder
    from backend import webrtc_server
    if not webrtc_server.WEBRTC_DISPONIBLE:
        raise RuntimeError("webrtc_server arranco sin WebRTC (aiortc no importa)")
    for nombre, encoder in (("VP8", Vp8Encoder()), ("H264", H264Encoder())):
        frame = av.VideoFrame.from_ndarray(
            np.zeros((480, 640, 3), dtype=np.uint8), format="bgr24")
        frame.pts = 0
        frame.time_base = fractions.Fraction(1, 90000)
        paquetes, _ = encoder.encode(frame)
        if not paquetes:
            raise RuntimeError(f"el codificador {nombre} no produjo datos")
    return f"aiortc + PyAV {av.__version__}, VP8 y H264 codifican"


def _realsense():
    import pyrealsense2 as rs
    import motor_ia.camara.realsense  # noqa: F401 - que el modulo real importe
    dispositivos = len(rs.context().query_devices())
    return f"SDK cargado, {dispositivos} camara(s) RealSense conectada(s)"


def _onnx():
    import onnxruntime
    import motor_ia.reconocimiento.motor_onnx  # noqa: F401
    proveedores = onnxruntime.get_available_providers()
    if "CPUExecutionProvider" not in proveedores:
        raise RuntimeError(f"sin proveedor CPU: {proveedores}")
    return f"onnxruntime {onnxruntime.__version__}"


def _supabase():
    from supabase import create_client
    import backend.supabase_sync, backend.heartbeat  # noqa: F401,E401
    import backend.command_listener, backend.cleanup  # noqa: F401,E401
    # Construir el cliente no conecta: solo comprueba que el SDK y sus
    # dependencias (httpx, realtime, storage) estan completos.
    create_client("https://autoprueba.supabase.co", "autoprueba")
    return "SDK de Supabase completo (sin conectar)"


def _pipeline():
    import motor_ia.pipeline  # noqa: F401 - arrastra todo el motor de IA
    return "motor_ia.pipeline importa"


COMPROBACIONES = (
    ("Carpeta de datos", _carpeta_datos),
    ("OpenCV", _opencv),
    ("MediaPipe", _mediapipe),
    ("dlib / face_recognition", _dlib),
    ("WebRTC", _webrtc),
    ("RealSense", _realsense),
    ("ONNX Runtime", _onnx),
    ("Supabase", _supabase),
    ("Pipeline", _pipeline),
)


def ejecutar(comprobaciones=COMPROBACIONES, salida=print):
    salida(f"DepthGuard - autoprueba (Python {sys.version.split()[0]})")
    fallos = 0
    for nombre, comprobar in comprobaciones:
        inicio = time.perf_counter()
        try:
            detalle = comprobar()
            estado = "OK   "
        # SystemExit a proposito: face_recognition llama a quit() (codigo 0)
        # si no encuentra sus modelos, en vez de lanzar un error.
        except (Exception, SystemExit) as e:  # noqa: BLE001
            detalle = f"{type(e).__name__}: {e}"
            estado = "FALLO"
            fallos += 1
        salida(f"  [{estado}] {nombre}: {detalle} "
               f"({time.perf_counter() - inicio:.1f} s)")

    if fallos:
        salida(f"AUTOPRUEBA FALLIDA: {fallos} de {len(comprobaciones)} comprobaciones")
        return 1
    salida(f"AUTOPRUEBA OK: {len(comprobaciones)} comprobaciones")
    return 0
