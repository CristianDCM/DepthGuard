"""
Camara simulada: webcam normal, SIN profundidad.

Antes esta clase fabricaba un mapa de profundidad a partir del bbox que ya
habia detectado el pipeline (`actualizar_profundidad`). Eso convertia el
anti-spoofing 3D en una tautologia: el verificador validaba una cupula que el
propio sistema acababa de dibujar, asi que cualquier rostro detectado pasaba
como "real" —foto impresa incluida— y siempre con las mismas metricas
(distancia 68.8 cm, varianza 1.57, rango 4.1 en cualquier situacion).

Ahora devuelve profundidad None y lo declara con `profundidad_real = False`.
El pipeline no ejecuta el verificador 3D sin datos reales; la prueba de vida
en este modo la aporta motor_ia/antispoofing/liveness.py (parpadeo).
"""

import cv2


class CamaraSimulada:

    # Esta camara no mide profundidad. El pipeline lo consulta para decidir
    # si puede ejecutar el verificador 3D y para no reportar metricas 3D
    # inventadas a Supabase.
    profundidad_real = False

    def __init__(self):
        self.webcam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.webcam.isOpened():
            # Fallback sin DirectShow
            self.webcam = cv2.VideoCapture(0)
        if not self.webcam.isOpened():
            raise RuntimeError("No se detecto webcam")

        # Forzar resolucion 640x480 para rendimiento
        self.webcam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        # Reducir buffer interno de la webcam a 1 frame (menor latencia)
        self.webcam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def conectar(self):
        print(" Camara SIMULADA conectada (webcam 640x480, sin profundidad)")
        print("    Anti-spoofing 3D NO disponible en este modo.")
        print("    Prueba de vida por parpadeo (liveness 2D).")

    def obtener_frames(self):
        """Retorna (color, None). No hay mapa de profundidad que devolver."""
        ret, frame = self.webcam.read()
        if not ret:
            return None, None
        return frame, None

    def cerrar(self):
        self.webcam.release()
        print(" Camara simulada cerrada")
