"""Detección facial con MediaPipe Face Mesh (multi-rostro)."""

from collections import namedtuple

import mediapipe as mp
import numpy as np


# Resultado de detección para un rostro.
# Es una namedtuple para que siga siendo desempaquetable como tupla,
# pero con acceso por nombre en el pipeline.
RostroDetectado = namedtuple(
    "RostroDetectado",
    ["bbox", "angulo_h", "angulo_v", "direccion", "puntos"]
)

# Margen del bbox como fracción del tamaño del rostro.
#
# Antes era un margen FIJO de 25px, lo que hacía que la escala relativa del
# crop cambiara con la distancia: en un rostro de 200px el margen era +12%,
# y en uno de 70px era +36%. Los embeddings faciales son muy sensibles a esa
# inconsistencia de encuadre, así que el margen debe ser proporcional.
MARGEN_REL = 0.12

# Índices de landmarks usados para el cálculo de ángulos.
_LM_NARIZ = 1
_LM_OJO_IZQ = 33
_LM_OJO_DER = 263
_LM_MENTON = 152


class DetectorFaceMesh:

    def __init__(self, max_rostros=5, confianza=0.5):
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=max_rostros,
            refine_landmarks=False,
            min_detection_confidence=confianza,
            min_tracking_confidence=confianza
        )

    def detectar(self, imagen_rgb):
        """
        Detecta todos los rostros visibles en el frame.

        Retorna lista de RostroDetectado(bbox, angulo_h, angulo_v,
        direccion, puntos) por cada rostro. Lista vacía si no hay rostros.

        bbox = (x, y, x2, y2) en píxeles del frame recibido
        direccion: "frontal", "izquierda", "derecha", "arriba", "abajo"
        puntos: array (N, 2) de landmarks en píxeles, reutilizable para
                alineación, calidad o liveness sin volver a leer protobuf.
        """
        alto, ancho = imagen_rgb.shape[:2]
        # Optimización oficial MediaPipe: evita copia interna del array
        imagen_rgb.flags.writeable = False
        resultado = self.face_mesh.process(imagen_rgb)
        imagen_rgb.flags.writeable = True

        if not resultado.multi_face_landmarks:
            return []

        rostros = []
        for landmarks in resultado.multi_face_landmarks:
            # Leer los landmarks UNA sola vez a numpy; todo lo demás
            # (bbox, ángulos) se calcula sobre este array.
            puntos = np.array(
                [(lm.x * ancho, lm.y * alto) for lm in landmarks.landmark],
                dtype=np.float32
            )

            bbox = calcular_bbox(puntos, ancho, alto)
            angulo_h, angulo_v, direccion = calcular_angulo(puntos)
            rostros.append(
                RostroDetectado(bbox, angulo_h, angulo_v, direccion, puntos)
            )

        return rostros

    def cerrar(self):
        self.face_mesh.close()


def calcular_bbox(puntos, ancho, alto, margen_rel=MARGEN_REL):
    """
    Bbox a partir de la envolvente de TODOS los landmarks, con margen
    proporcional al tamaño del rostro.

    Usar los 468 puntos (y no 9) hace que el bbox no salte cuando alguno
    de esos 9 puntos concretos se estima mal; el margen relativo mantiene
    la escala del crop constante a cualquier distancia.

    Args:
        puntos: array (N, 2) de landmarks en píxeles.
        ancho, alto: dimensiones del frame, para recortar el bbox.
        margen_rel: margen como fracción del lado del rostro.

    Returns:
        (x, y, x2, y2) enteros dentro del frame.
    """
    x_min, y_min = puntos.min(axis=0)
    x_max, y_max = puntos.max(axis=0)

    margen_x = (x_max - x_min) * margen_rel
    margen_y = (y_max - y_min) * margen_rel

    return (
        max(0, int(x_min - margen_x)),
        max(0, int(y_min - margen_y)),
        min(ancho, int(x_max + margen_x)),
        min(alto, int(y_max + margen_y))
    )


def calcular_angulo(puntos):
    """
    Calcula ángulo horizontal (yaw) y vertical (pitch) del rostro.
    Retorna (angulo_horizontal, angulo_vertical, direccion).

    Direcciones posibles: "frontal", "izquierda", "derecha", "arriba", "abajo"
    """
    # === Ángulo horizontal (yaw) ===
    nariz_x, nariz_y = puntos[_LM_NARIZ]
    ojo_izq_x, ojo_izq_y = puntos[_LM_OJO_IZQ]
    ojo_der_x, ojo_der_y = puntos[_LM_OJO_DER]

    centro_x = (ojo_izq_x + ojo_der_x) / 2
    dist_ojos = abs(ojo_der_x - ojo_izq_x)

    if dist_ojos < 1:
        return 0.0, 0.0, "frontal"

    despl_h = (nariz_x - centro_x) / dist_ojos
    angulo_h = round(float(despl_h) * 60, 1)

    # === Ángulo vertical (pitch) ===
    centro_ojos_y = (ojo_izq_y + ojo_der_y) / 2
    menton_y = puntos[_LM_MENTON][1]

    # Distancia vertical entre ojos y mentón como referencia
    dist_vertical = abs(menton_y - centro_ojos_y)

    if dist_vertical < 1:
        return angulo_h, 0.0, "frontal"

    # Posición relativa de la nariz entre ojos y mentón
    ratio_nariz = (nariz_y - centro_ojos_y) / dist_vertical
    angulo_v = round(float(ratio_nariz - 0.45) * 100, 1)

    # Determinar dirección predominante
    umbral_h = 10
    umbral_v = 8

    if angulo_h < -umbral_h:
        return angulo_h, angulo_v, "derecha"
    elif angulo_h > umbral_h:
        return angulo_h, angulo_v, "izquierda"
    elif angulo_v < -umbral_v:
        return angulo_h, angulo_v, "arriba"
    elif angulo_v > umbral_v:
        return angulo_h, angulo_v, "abajo"

    return angulo_h, angulo_v, "frontal"
