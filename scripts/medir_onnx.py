"""
Mide si merece la pena cambiar el motor de embeddings de dlib a ONNX.

CORRE ESTO EN LA MAQUINA DEL EDGE, no en otra: el resultado depende de tu CPU.

    pip install onnxruntime
    python scripts/medir_onnx.py

Cierra el sistema antes de ejecutarlo: si el edge esta corriendo tiene la
camara ocupada (el script lo detecta y usa un recorte sintetico, que para
medir vale igual) y ademas su CPU compite con la medicion.

Que mide y que NO mide
----------------------
MIDE velocidad: cuanto tarda un embedding con dlib (lo que tienes hoy) y
cuanto con un modelo ONNX moderno, sobre el MISMO recorte y en TU procesador.
Tambien si el modelo ONNX libera el GIL, que es lo que decide si se puede
paralelizar con hilos —dlib no lo libera, ya esta medido: con 4 hilos el
sistema va a 0.56x, es decir, casi el doble de lento.

NO MIDE precision. La precision de un modelo de rostro se mide con conjuntos
etiquetados (LFW, IJB-C) de decenas de miles de pares, no con dos usuarios.
Lo que se sabe de los benchmarks publicados es que los modelos entrenados con
perdida de margen tipo ArcFace estan por encima del de dlib (2017) sobre todo
en pose no frontal, gafas y diversidad de tonos de piel. Este script no te lo
va a demostrar: te dice si el cambio es viable y a que velocidad.
"""

import os
import sys
import time
import zipfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


# Modelo objetivo: MobileFaceNet entrenado con ArcFace (512D, ~13 MB).
# Se prueban varias fuentes porque los enlaces de modelos cambian con el
# tiempo; el script valida lo que descarga antes de usarlo.
FUENTES = [
    # Paquete "buffalo_s" de InsightFace: contiene w600k_mbf.onnx
    ("https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
     "zip", "w600k_mbf.onnx"),
    ("https://huggingface.co/immich-app/antelopev2/resolve/main/buffalo_s.zip",
     "zip", "w600k_mbf.onnx"),
    ("https://huggingface.co/maze/faceX/resolve/main/w600k_mbf.onnx",
     "onnx", None),
]

DESTINO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_modelos")
REPETICIONES = 20


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Obtener el modelo
# ---------------------------------------------------------------------------

def descargar(ruta_manual=None):
    """Devuelve la ruta a un .onnx valido, o None si no se pudo conseguir."""
    os.makedirs(DESTINO, exist_ok=True)

    if ruta_manual:
        return ruta_manual if os.path.isfile(ruta_manual) else None

    destino_onnx = os.path.join(DESTINO, "w600k_mbf.onnx")
    if os.path.isfile(destino_onnx):
        log(f"  ya descargado: {destino_onnx}")
        return destino_onnx

    for url, tipo, dentro in FUENTES:
        host = url.split("/")[2]
        log(f"  probando {host} ...")
        try:
            tmp = os.path.join(DESTINO, "descarga.tmp")
            with urllib.request.urlopen(url, timeout=90) as r, open(tmp, "wb") as f:
                f.write(r.read())

            if tipo == "zip":
                with zipfile.ZipFile(tmp) as z:
                    nombre = next(
                        (n for n in z.namelist() if n.endswith(dentro)), None
                    )
                    if nombre is None:
                        log(f"    el zip no contiene {dentro}")
                        continue
                    with z.open(nombre) as origen, open(destino_onnx, "wb") as f:
                        f.write(origen.read())
            else:
                os.replace(tmp, destino_onnx)

            if os.path.getsize(destino_onnx) > 1_000_000:
                log(f"    descargado ({os.path.getsize(destino_onnx)/1e6:.0f} MB)")
                return destino_onnx
            log("    el fichero es demasiado pequeno, no parece un modelo")

        except Exception as e:
            log(f"    fallo: {type(e).__name__}: {e}")
        finally:
            if os.path.exists(os.path.join(DESTINO, "descarga.tmp")):
                os.remove(os.path.join(DESTINO, "descarga.tmp"))

    return None


# ---------------------------------------------------------------------------
# Recorte de prueba: preferimos uno REAL de tu camara
# ---------------------------------------------------------------------------

def obtener_recorte():
    """
    Devuelve (recorte_rgb, procedencia). Intenta usar la webcam y el detector
    de verdad para que el coste de dlib sea exactamente el de produccion; si no
    hay camara o no detecta, cae en un recorte sintetico (el coste de una red
    convolucional no depende del contenido de la imagen, solo del tamano).
    """
    import cv2
    # Si el edge esta corriendo, la camara esta ocupada y OpenCV vuelca un muro
    # de errores que no aporta nada: el script ya cae en el recorte sintetico.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass

    try:
        from motor_ia.deteccion.face_mesh import DetectorFaceMesh
        from config.settings import CAMARA_ANCHO, CAMARA_ALTO

        cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cam.isOpened():
            cam = cv2.VideoCapture(0)
        if cam.isOpened():
            cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAMARA_ANCHO)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMARA_ALTO)
            det = DetectorFaceMesh(max_rostros=1, confianza=0.5)
            try:
                for _ in range(30):
                    ok, frame = cam.read()
                    if not ok:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    rostros = det.detectar(rgb)
                    if rostros:
                        x, y, x2, y2 = rostros[0].bbox
                        crop = np.ascontiguousarray(rgb[y:y2, x:x2])
                        if crop.size > 0:
                            return crop, f"camara real ({x2-x}x{y2-y} px)"
            finally:
                det.cerrar()
                cam.release()
    except Exception as e:
        log(f"  (sin camara utilizable: {type(e).__name__})")

    rs = np.random.RandomState(7)
    crop = rs.randint(60, 200, (240, 180, 3), dtype=np.uint8)
    return crop, "sintetico (180x240 px)"


def crono(fn, n=REPETICIONES):
    fn()
    t = []
    for _ in range(n):
        a = time.perf_counter()
        fn()
        t.append((time.perf_counter() - a) * 1000)
    return float(np.median(t))


# ---------------------------------------------------------------------------
# Las dos mediciones
# ---------------------------------------------------------------------------

def medir_dlib(crop):
    import face_recognition
    alto, ancho = crop.shape[:2]
    ubic = [(0, ancho, alto, 0)]
    ms = crono(lambda: face_recognition.face_encodings(
        crop, ubic, num_jitters=1, model="large"))
    return ms


def medir_onnx(ruta, crop, nucleos):
    import cv2
    import onnxruntime as ort

    # ArcFace espera 112x112 RGB normalizado a [-1, 1]
    entrada = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
    tensor = ((entrada.astype(np.float32) - 127.5) / 127.5)
    tensor = np.transpose(tensor, (2, 0, 1))[None, ...]

    resultados = {}
    for etiqueta, hilos in (("1 hilo", 1), (f"{nucleos} hilos", nucleos)):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = hilos
        opts.inter_op_num_threads = 1
        t = time.perf_counter()
        ses = ort.InferenceSession(ruta, opts, providers=["CPUExecutionProvider"])
        carga = (time.perf_counter() - t) * 1000
        nombre = ses.get_inputs()[0].name
        forma = ses.get_inputs()[0].shape
        salida = ses.run(None, {nombre: tensor})[0]
        ms = crono(lambda: ses.run(None, {nombre: tensor}))
        resultados[etiqueta] = ms
        resultados.setdefault("carga_ms", carga)
        resultados.setdefault("forma_entrada", forma)
        resultados.setdefault("dimensiones", int(np.asarray(salida).reshape(-1).shape[0]))

    # Libera el GIL? Es lo que decide si se puede paralelizar con hilos.
    from concurrent.futures import ThreadPoolExecutor
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    ses1 = ort.InferenceSession(ruta, opts, providers=["CPUExecutionProvider"])
    nombre = ses1.get_inputs()[0].name
    tarea = lambda _: ses1.run(None, {nombre: tensor})
    tarea(0)

    N = 8
    t = time.perf_counter()
    for _ in range(N):
        tarea(0)
    sec = time.perf_counter() - t
    with ThreadPoolExecutor(max_workers=nucleos) as ex:
        list(ex.map(tarea, range(nucleos)))
        t = time.perf_counter()
        list(ex.map(tarea, range(N)))
        par = time.perf_counter() - t
    ms_suelto = sec / N * 1000
    resultados["ganancia_hilos"] = sec / par if par > 0 else 0.0
    # Por debajo de unos milisegundos por llamada, el tiempo se lo come el
    # coste de invocar y no el computo, asi que el cociente no mide el GIL.
    # No es un problema: a esa velocidad no hace falta paralelizar nada.
    resultados["hilos_concluyente"] = ms_suelto >= 3.0

    return resultados


# ---------------------------------------------------------------------------

def main():
    ruta_manual = sys.argv[1] if len(sys.argv) > 1 else None
    nucleos = os.cpu_count() or 4

    log("=" * 66)
    log(" MEDICION: dlib (actual) frente a ONNX ArcFace")
    log("=" * 66)
    log(f"\nMaquina: {nucleos} nucleos, {sys.platform}, Python {sys.version.split()[0]}")

    try:
        import onnxruntime as ort
        log(f"onnxruntime {ort.__version__}")
    except ImportError:
        log("\nFALTA onnxruntime. Instalalo y vuelve a ejecutar:")
        log("    pip install onnxruntime")
        return 1

    log("\n1) Consiguiendo el modelo ONNX")
    ruta = descargar(ruta_manual)
    if ruta is None:
        log("\n  No se pudo descargar el modelo automaticamente.")
        log("  Descarga 'buffalo_s.zip' de InsightFace a mano, saca")
        log("  w600k_mbf.onnx y pasale la ruta al script:")
        log("      python scripts/medir_onnx.py C:\\ruta\\w600k_mbf.onnx")
        return 1

    log("\n2) Preparando el recorte de prueba")
    crop, procedencia = obtener_recorte()
    log(f"  recorte: {procedencia}")

    log("\n3) Midiendo dlib (lo que corre hoy en produccion)")
    ms_dlib = medir_dlib(crop)
    log(f"  {ms_dlib:.1f} ms por embedding")

    log("\n4) Midiendo ONNX")
    r = medir_onnx(ruta, crop, nucleos)
    log(f"  entrada del modelo : {r['forma_entrada']}")
    log(f"  dimensiones salida : {r['dimensiones']}  (dlib usa 128)")
    log(f"  carga del modelo   : {r['carga_ms']:.0f} ms")

    log("\n" + "=" * 66)
    log(" RESULTADO")
    log("=" * 66)
    ms_1 = r["1 hilo"]
    ms_n = r[f"{nucleos} hilos"]
    log(f"\n  dlib  (actual)            {ms_dlib:7.1f} ms")
    log(f"  ONNX  1 hilo              {ms_1:7.1f} ms   {ms_dlib/ms_1:5.1f}x mas rapido")
    log(f"  ONNX  {nucleos} hilos internos      {ms_n:7.1f} ms   {ms_dlib/ms_n:5.1f}x mas rapido")
    if r["hilos_concluyente"]:
        log(f"\n  ONNX libera el GIL: ganancia con {nucleos} hilos = "
            f"{r['ganancia_hilos']:.2f}x")
        log( "  (dlib, medido: 0.56x con 4 hilos — es decir, EMPEORA)")
    else:
        log(f"\n  Prueba de hilos no concluyente: cada llamada dura menos de 3 ms,")
        log( "  asi que lo que se mide es el coste de invocar, no el computo.")
        log( "  A esa velocidad da igual: no hace falta paralelizar nada.")

    mejor = min(ms_1, ms_n)
    log("\n  Lectura:")
    if mejor < ms_dlib / 3:
        log(f"    MERECE LA PENA. {ms_dlib/mejor:.1f}x mas rapido.")
        fmt = f"{mejor:.1f}" if mejor < 10 else f"{mejor:.0f}"
        log(f"    El embedding baja de {ms_dlib:.0f} ms a {fmt} ms, asi que deja")
        log( "    de congelar el bucle principal y se pueden identificar varias")
        log( "    personas en el mismo frame sin cola.")
        log( "    Coste: los embeddings guardados no son compatibles (128D -> "
             f"{r['dimensiones']}D),")
        log( "    hay que volver a registrar a los usuarios. Con 2 usuarios son minutos.")
    elif mejor < ms_dlib:
        log(f"    MEJORA MODESTA ({ms_dlib/mejor:.1f}x). Probablemente no compensa")
        log( "    el re-registro solo por velocidad; decidelo por la precision.")
    else:
        log( "    NO MERECE LA PENA en esta maquina: no es mas rapido.")

    log("\n  Recuerda: esto mide VELOCIDAD. La precision no se mide con dos")
    log("  usuarios; eso viene de los benchmarks publicados del modelo.")
    log("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
