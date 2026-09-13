"""
Validación de calidad facial.

Verifica que el recorte facial cumple requisitos mínimos de calidad
ANTES de generar el embedding.

Se usa en dos sitios con dos perfiles de umbrales distintos:

  * REGISTRO (estricto): garantiza que los embeddings de referencia
    guardados en la base de datos sean de alta calidad. Si el frame no
    sirve, se le pide a la persona que lo repita — no hay coste.

  * RECONOCIMIENTO (laxo): descarta frames de los que no se puede sacar
    un embedding util (borroso, oscuro, rostro diminuto). Antes no se
    filtraba nada aqui, asi que esos frames generaban embeddings basura
    que luego competian en el matching. Rechazar es gratis: se reintenta
    en el siguiente ciclo.

Criterios:
  1. Tamaño mínimo del rostro
  2. Nitidez (Laplacian variance > umbral)
  3. Iluminación (brillo medio en rango aceptable)
  4. Contraste suficiente (desviación estándar > umbral)
"""

from collections import namedtuple

import cv2
import numpy as np


UmbralesCalidad = namedtuple(
    "UmbralesCalidad",
    ["min_size", "min_sharpness", "min_brightness", "max_brightness", "min_contrast"]
)


# === Umbrales de REGISTRO (estrictos) ===
#
# min_size: lado minimo del crop facial en pixeles
# min_sharpness: varianza del Laplaciano. Menor = mas borroso.
#     < 30 = muy borroso, 30-60 = aceptable, > 60 = nitido
# brillo: escala 0-255. Muy oscuro < 40, ideal 60-200, muy brillante > 220
# min_contrast: desviacion estandar del gris. < 15 = imagen plana
UMBRALES_REGISTRO = UmbralesCalidad(
    min_size=80,
    min_sharpness=25.0,
    min_brightness=40,
    max_brightness=220,
    min_contrast=15.0,
)

# === Umbrales de RECONOCIMIENTO (laxos) ===
#
# Aqui no buscamos una buena plantilla, solo descartar lo inservible.
UMBRALES_RECONOCIMIENTO = UmbralesCalidad(
    min_size=60,
    min_sharpness=12.0,
    min_brightness=25,
    max_brightness=235,
    min_contrast=10.0,
)


# Alias retrocompatibles (los valores de registro son los historicos)
MIN_FACE_SIZE = UMBRALES_REGISTRO.min_size
MIN_SHARPNESS = UMBRALES_REGISTRO.min_sharpness
MIN_BRIGHTNESS = UMBRALES_REGISTRO.min_brightness
MAX_BRIGHTNESS = UMBRALES_REGISTRO.max_brightness
MIN_CONTRAST = UMBRALES_REGISTRO.min_contrast


def validar_calidad_rostro(imagen_rgb, bbox, umbrales=UMBRALES_REGISTRO):
    """
    Valida la calidad del recorte facial.

    Args:
        imagen_rgb: Frame completo en RGB (numpy array).
        bbox: Tuple (x, y, x2, y2) del bounding box del rostro.
        umbrales: UmbralesCalidad a aplicar (registro por defecto).

    Returns:
        (es_valido, motivo): Tuple con bool y string descriptivo.
        Si es_valido es True, motivo contiene info de calidad.
        Si es_valido es False, motivo explica qué falló.
    """
    alto_img, ancho_img = imagen_rgb.shape[:2]
    x, y, x2, y2 = bbox

    # Acotar el bbox al frame ANTES de medir. Si no, un bbox que se sale por
    # un borde declara un tamaño que no tiene: numpy recorta el slice y el
    # crop real acaba siendo mucho más pequeño de lo anunciado.
    x = max(0, min(int(x), ancho_img))
    y = max(0, min(int(y), alto_img))
    x2 = max(0, min(int(x2), ancho_img))
    y2 = max(0, min(int(y2), alto_img))

    # Extraer crop facial y medir sobre él, no sobre el bbox pedido
    crop = imagen_rgb[y:y2, x:x2]

    if crop.size == 0:
        return False, "Crop facial vacío."

    alto, ancho = crop.shape[:2]

    # === 1. Tamaño mínimo ===
    if ancho < umbrales.min_size or alto < umbrales.min_size:
        return False, f"Rostro muy pequeño ({ancho}x{alto}px). Acérquese a la cámara."

    # Convertir a escala de grises para análisis
    gris = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

    # === 2. Nitidez (Laplacian variance) ===
    laplacian = cv2.Laplacian(gris, cv2.CV_64F)
    sharpness = laplacian.var()

    if sharpness < umbrales.min_sharpness:
        return False, f"Imagen borrosa (nitidez: {sharpness:.0f}). Mantenga la cabeza quieta."

    # === 3. Iluminación (brillo medio) ===
    brillo = float(np.mean(gris))

    if brillo < umbrales.min_brightness:
        return False, f"Muy oscuro (brillo: {brillo:.0f}). Mejore la iluminación."

    if brillo > umbrales.max_brightness:
        return False, f"Muy brillante (brillo: {brillo:.0f}). Evite luz directa en el rostro."

    # === 4. Contraste (desviación estándar) ===
    contraste = float(np.std(gris))

    if contraste < umbrales.min_contrast:
        return False, f"Sin contraste (std: {contraste:.0f}). Revise la iluminación."

    # === Aprobado ===
    return True, (
        f"OK (size:{ancho}x{alto} sharp:{sharpness:.0f} "
        f"bright:{brillo:.0f} contrast:{contraste:.0f})"
    )


def apta_para_reconocimiento(imagen_rgb, bbox):
    """
    Gate laxo previo al reconocimiento. Retorna (es_valido, motivo).
    """
    return validar_calidad_rostro(imagen_rgb, bbox, UMBRALES_RECONOCIMIENTO)


def pose_apta_para_reconocimiento(angulo_h, angulo_v, max_yaw, max_pitch):
    """
    Comprueba que la pose esta dentro del rango en el que el embedding es
    fiable. Un rostro muy girado produce un vector que no se parece a
    ninguna plantilla — o, peor, se parece a la de otra persona.

    Retorna (es_apta, motivo).
    """
    if abs(angulo_h) > max_yaw:
        return False, f"Rostro muy girado (yaw: {angulo_h:.0f})"
    if abs(angulo_v) > max_pitch:
        return False, f"Rostro muy inclinado (pitch: {angulo_v:.0f})"
    return True, ""
