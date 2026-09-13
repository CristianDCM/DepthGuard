"""
Motor de embeddings con ONNX (MobileFaceNet entrenado con ArcFace).

Alternativa a dlib, seleccionable con MOTOR_EMBEDDING en .env. Medido en el
equipo del edge (16 nucleos, Windows):

    dlib                 217.5 ms
    ONNX 1 hilo            9.7 ms    22x
    ONNX 16 hilos          3.2 ms    69x

Y acepta lote dinamico, asi que las N caras de un frame van en una sola
llamada: 5 rostros en 26 ms frente a los ~1090 ms que costarian con dlib uno
detras de otro.

Dos avisos importantes
---------------------
1. Los embeddings NO son compatibles con los de dlib: 512 dimensiones en vez
   de 128, y otra geometria. Cambiar de motor obliga a volver a registrar a
   todos los usuarios. El codigo detecta la mezcla y avisa en vez de comparar
   vectores de motores distintos, que daria resultados sin sentido.

2. Los umbrales son distintos. Este motor devuelve vectores normalizados a
   norma 1, asi que la distancia euclidea entre dos de ellos esta acotada en
   [0, 2] y se relaciona con la similitud coseno por
       euclidea = sqrt(2 * (1 - coseno)).
   El umbral por defecto es una eleccion razonable, NO un valor calibrado con
   rostros reales: hay que ajustarlo (ver scripts/calibrar_umbral.py).
"""

import os

import cv2
import numpy as np


# Plantilla de referencia de ArcFace: donde deben acabar los 5 puntos en la
# imagen de 112x112 que espera el modelo. Son las coordenadas canonicas que usa
# InsightFace; cambiarlas desalinea el rostro respecto a como se entreno la red.
#
# Orden: ojo (lado izquierdo de la imagen), ojo (lado derecho), punta de la
# nariz, comisura izquierda de la boca, comisura derecha.
PLANTILLA_ARCFACE = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float64)

LADO_ENTRADA = 112

# Contornos de ojo de MediaPipe Face Mesh. Se reutilizan los del detector de
# parpadeo: el centro del ojo se toma como la media de sus 6 puntos, que es
# mas estable que un solo landmark.
from motor_ia.antispoofing.liveness import OJO_IZQ, OJO_DER  # noqa: E402

_LM_NARIZ = 1
_LM_BOCA_A = 61
_LM_BOCA_B = 291


def similaridad(origen, destino):
    """
    Transformacion de semejanza (rotacion + escala uniforme + traslacion) que
    lleva `origen` sobre `destino` por minimos cuadrados. Algoritmo de Umeyama.

    Se implementa aqui en vez de usar cv2.estimateAffinePartial2D porque ese
    aplica RANSAC/LMEDS y puede descartar puntos: con solo 5 correspondencias,
    descartar uno cambia bastante el encuadre y lo hace de forma no
    determinista. InsightFace alinea con una semejanza por minimos cuadrados
    sobre los 5 puntos, sin rechazo, y es lo que replicamos.

    Returns:
        Matriz 2x3 apta para cv2.warpAffine.
    """
    origen = np.asarray(origen, dtype=np.float64)
    destino = np.asarray(destino, dtype=np.float64)

    centro_o = origen.mean(axis=0)
    centro_d = destino.mean(axis=0)
    o = origen - centro_o
    d = destino - centro_d

    varianza = (o ** 2).sum() / len(o)
    covarianza = (d.T @ o) / len(o)

    u, s, vt = np.linalg.svd(covarianza)

    # Si el determinante es negativo la SVD ha colado una reflexion. Una
    # semejanza no refleja: sin esta correccion un rostro podria alinearse
    # espejado, y el modelo veria una cara que no es la que hay.
    correccion = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        correccion[1, 1] = -1.0

    rotacion = u @ correccion @ vt
    escala = 1.0 if varianza == 0 else float(np.trace(np.diag(s) @ correccion) / varianza)

    matriz = np.zeros((2, 3), dtype=np.float64)
    matriz[:, :2] = escala * rotacion
    matriz[:, 2] = centro_d - (escala * rotacion) @ centro_o
    return matriz


def cinco_puntos(puntos):
    """
    Extrae de los 468 landmarks de Face Mesh los 5 que usa ArcFace.

    Los pares se ordenan por coordenada x en vez de fiarse de que un indice
    concreto sea "el ojo izquierdo". Que indice cae a que lado depende de si la
    imagen esta espejada, y equivocarse intercambia los dos ojos: la
    transformacion resultante gira el rostro 180 grados y el embedding sale de
    una cara del reves. Ordenar por x lo hace correcto en ambos casos.

    Supone que el rostro no esta inclinado mas de ~90 grados, lo que el gate de
    pose del pipeline ya garantiza de sobra.

    Args:
        puntos: array (N, 2) de landmarks en pixeles.

    Returns:
        array (5, 2) en el orden que espera PLANTILLA_ARCFACE.
    """
    puntos = np.asarray(puntos, dtype=np.float64)

    ojo_a = puntos[list(OJO_IZQ)].mean(axis=0)
    ojo_b = puntos[list(OJO_DER)].mean(axis=0)
    ojo_izq, ojo_der = sorted((ojo_a, ojo_b), key=lambda p: p[0])

    boca_a = puntos[_LM_BOCA_A]
    boca_b = puntos[_LM_BOCA_B]
    boca_izq, boca_der = sorted((boca_a, boca_b), key=lambda p: p[0])

    return np.array([ojo_izq, ojo_der, puntos[_LM_NARIZ], boca_izq, boca_der],
                    dtype=np.float64)


def alinear(imagen_rgb, puntos):
    """
    Recorta y alinea el rostro a los 112x112 que espera el modelo.

    Devuelve la imagen alineada en RGB uint8.
    """
    matriz = similaridad(cinco_puntos(puntos), PLANTILLA_ARCFACE)
    return cv2.warpAffine(
        imagen_rgb, matriz.astype(np.float32), (LADO_ENTRADA, LADO_ENTRADA),
        flags=cv2.INTER_LINEAR, borderValue=0.0,
    )


def alinear_por_bbox(imagen_rgb, bbox):
    """
    Alineacion de emergencia cuando no hay landmarks: escalar el recorte.

    Es notablemente peor —el modelo se entreno con rostros alineados por los 5
    puntos— y solo existe para que el sistema siga funcionando en lugar de
    fallar si algun camino no trae los puntos.
    """
    x, y, x2, y2 = bbox
    recorte = imagen_rgb[max(0, y):y2, max(0, x):x2]
    if recorte.size == 0:
        return np.zeros((LADO_ENTRADA, LADO_ENTRADA, 3), dtype=np.uint8)
    return cv2.resize(recorte, (LADO_ENTRADA, LADO_ENTRADA),
                      interpolation=cv2.INTER_AREA)


def preprocesar(alineada):
    """
    De imagen alineada uint8 RGB al tensor que espera el modelo.

    Normaliza a [-1, 1] y pasa a formato NCHW. El modelo se entreno con RGB
    (InsightFace usa swapRB=True sobre imagenes BGR de OpenCV), y aqui la
    imagen ya llega en RGB, asi que no hay que intercambiar canales.
    """
    t = (alineada.astype(np.float32) - 127.5) / 127.5
    return np.transpose(t, (2, 0, 1))


class MotorONNX:
    """Genera embeddings de 512 dimensiones, normalizados a norma 1."""

    dimensiones = 512
    nombre = "onnx"

    def __init__(self, ruta_modelo, hilos=0):
        if not os.path.isfile(ruta_modelo):
            raise FileNotFoundError(
                f"No encuentro el modelo ONNX en {ruta_modelo}.\n"
                "   Descargalo con: python scripts/descargar_modelo.py"
            )

        try:
            import onnxruntime as ort
        except ImportError as e:
            raise ImportError(
                "Falta onnxruntime. Instalalo con: pip install onnxruntime"
            ) from e

        opciones = ort.SessionOptions()
        if hilos > 0:
            opciones.intra_op_num_threads = hilos
        opciones.inter_op_num_threads = 1

        # Solo errores. El modelo declara su salida como [1, 512] aunque acepte
        # lote dinamico en la entrada, asi que con un lote de N emite un aviso
        # "Expected shape {1,512} does not match actual shape {N,512}" por cada
        # inferencia. La salida es correcta —se verifico que devuelve (N, 512)—
        # pero sin esto el log del edge se llenaria de avisos inofensivos.
        opciones.log_severity_level = 3

        self.sesion = ort.InferenceSession(
            ruta_modelo, opciones, providers=["CPUExecutionProvider"]
        )
        self.entrada = self.sesion.get_inputs()[0].name
        self.ruta = ruta_modelo

    def generar(self, imagen_rgb, bbox, puntos=None):
        """Embedding de un rostro. Devuelve un vector (512,) de norma 1."""
        vectores = self.generar_lote(imagen_rgb, [(bbox, puntos)])
        return vectores[0] if len(vectores) else None

    def generar_lote(self, imagen_rgb, rostros):
        """
        Embeddings de VARIOS rostros del mismo frame en una sola inferencia.

        Es la razon de ser de este motor para el caso multi-rostro: el coste
        por rostro baja al agrupar (medido: 7.6 ms un rostro, 26 ms cinco, o
        sea 5.2 ms cada uno).

        Args:
            imagen_rgb: frame completo.
            rostros: lista de (bbox, puntos). puntos puede ser None.

        Returns:
            array (N, 512) normalizado por filas.
        """
        if not rostros:
            return np.zeros((0, self.dimensiones), dtype=np.float32)

        tensores = []
        for bbox, puntos in rostros:
            if puntos is not None and len(puntos) > max(_LM_BOCA_B, _LM_NARIZ):
                alineada = alinear(imagen_rgb, puntos)
            else:
                alineada = alinear_por_bbox(imagen_rgb, bbox)
            tensores.append(preprocesar(alineada))

        lote = np.stack(tensores).astype(np.float32)
        salida = self.sesion.run(None, {self.entrada: lote})[0]
        salida = np.asarray(salida, dtype=np.float64).reshape(len(rostros), -1)

        # Normalizar a norma 1 para que la distancia euclidea entre embeddings
        # equivalga a la similitud coseno: euclidea = sqrt(2*(1-coseno)). Asi
        # el matching que ya existe (que mide distancia euclidea) sirve tal
        # cual, y lo unico que cambia son los umbrales.
        normas = np.linalg.norm(salida, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        return salida / normas
