"""
Validación de calidad facial para registro biométrico.

Verifica que el recorte facial cumple requisitos mínimos de calidad
ANTES de generar el embedding. Esto garantiza que los embeddings
de referencia en la base de datos sean de alta calidad.

Criterios:
  1. Tamaño mínimo del rostro (100×100 px)
  2. Nitidez (Laplacian variance > umbral)
  3. Iluminación (brillo medio en rango aceptable)
  4. Contraste suficiente (desviación estándar > umbral)
"""

import cv2
import numpy as np


# === Umbrales de calidad ===

# Tamaño mínimo del crop facial en píxeles (ancho o alto)
MIN_FACE_SIZE = 80

# Nitidez: varianza del Laplaciano. Menor = más borroso.
# < 30 = muy borroso, 30-60 = aceptable, > 60 = nítido
MIN_SHARPNESS = 25.0

# Brillo medio del crop (escala 0-255).
# Muy oscuro < 40, ideal 60-200, muy brillante > 220
MIN_BRIGHTNESS = 40
MAX_BRIGHTNESS = 220

# Contraste: desviación estándar de los valores de gris.
# < 15 = imagen plana (sin contraste), > 15 = aceptable
MIN_CONTRAST = 15.0


def validar_calidad_rostro(imagen_rgb, bbox):
    """
    Valida la calidad del recorte facial para registro.

    Args:
        imagen_rgb: Frame completo en RGB (numpy array).
        bbox: Tuple (x, y, x2, y2) del bounding box del rostro.

    Returns:
        (es_valido, motivo): Tuple con bool y string descriptivo.
        Si es_valido es True, motivo contiene info de calidad.
        Si es_valido es False, motivo explica qué falló.
    """
    x, y, x2, y2 = bbox
    ancho = x2 - x
    alto = y2 - y

    # === 1. Tamaño mínimo ===
    if ancho < MIN_FACE_SIZE or alto < MIN_FACE_SIZE:
        return False, f"Rostro muy pequeño ({ancho}x{alto}px). Acérquese a la cámara."

    # Extraer crop facial
    crop = imagen_rgb[y:y2, x:x2]

    if crop.size == 0:
        return False, "Crop facial vacío."

    # Convertir a escala de grises para análisis
    gris = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

    # === 2. Nitidez (Laplacian variance) ===
    laplacian = cv2.Laplacian(gris, cv2.CV_64F)
    sharpness = laplacian.var()

    if sharpness < MIN_SHARPNESS:
        return False, f"Imagen borrosa (nitidez: {sharpness:.0f}). Mantenga la cabeza quieta."

    # === 3. Iluminación (brillo medio) ===
    brillo = float(np.mean(gris))

    if brillo < MIN_BRIGHTNESS:
        return False, f"Muy oscuro (brillo: {brillo:.0f}). Mejore la iluminación."

    if brillo > MAX_BRIGHTNESS:
        return False, f"Muy brillante (brillo: {brillo:.0f}). Evite luz directa en el rostro."

    # === 4. Contraste (desviación estándar) ===
    contraste = float(np.std(gris))

    if contraste < MIN_CONTRAST:
        return False, f"Sin contraste (std: {contraste:.0f}). Revise la iluminación."

    # === Aprobado ===
    return True, (
        f"OK (size:{ancho}x{alto} sharp:{sharpness:.0f} "
        f"bright:{brillo:.0f} contrast:{contraste:.0f})"
    )
