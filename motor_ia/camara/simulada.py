"""Cámara simulada usando webcam + profundidad artificial."""

import cv2
import numpy as np


class CamaraSimulada:

    def __init__(self):
        self.webcam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.webcam.isOpened():
            # Fallback sin DirectShow
            self.webcam = cv2.VideoCapture(0)
        if not self.webcam.isOpened():
            raise RuntimeError("No se detectó webcam")

        # Forzar resolución 640x480 para rendimiento
        self.webcam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        # Reducir buffer interno de la webcam a 1 frame (menor latencia)
        self.webcam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.modo = "REAL"
        # Cache de profundidad para reusar entre frames sin rostro
        self._prof_cache = None
        self._prof_shape = None
        # Pre-computar malla de coordenadas (se ajusta al primer frame)
        self._mesh_y = None
        self._mesh_x = None

    def conectar(self):
        print("✅ Cámara SIMULADA conectada (webcam 640x480)")

    def obtener_frames(self):
        ret, frame = self.webcam.read()
        if not ret:
            return None, None

        alto, ancho = frame.shape[:2]

        # Inicializar mesh una sola vez
        if self._mesh_y is None or self._prof_shape != (alto, ancho):
            self._prof_shape = (alto, ancho)
            self._mesh_y, self._mesh_x = np.mgrid[0:alto, 0:ancho]

        if self.modo == "REAL":
            prof = self._profundidad_real(frame, alto, ancho)
        elif self.modo == "FRAUDE":
            prof = self._profundidad_plana(alto, ancho)
        else:
            prof = self._profundidad_lejos(alto, ancho)

        return frame, prof

    def actualizar_profundidad(self, bbox):
        """Actualiza la profundidad sintética usando un bbox ya detectado por el pipeline.
        Llamar desde pipeline.py para evitar correr un segundo detector."""
        if bbox is None or self._prof_shape is None:
            return
        alto, ancho = self._prof_shape
        x, y, x2, y2 = bbox
        w = x2 - x
        h = y2 - y
        if w < 10 or h < 10:
            return

        cx, cy = x + w // 2, y + h // 2

        # Vectorizado: generar profundidad 3D solo en la región del rostro
        reg_y = self._mesh_y[y:y2, x:x2]
        reg_x = self._mesh_x[y:y2, x:x2]

        dy = np.abs(reg_y - cy).astype(np.float32) / max(h / 2, 1)
        dx = np.abs(reg_x - cx).astype(np.float32) / max(w / 2, 1)

        depth_region = (670 + (dx**2 + dy**2) * 60).astype(np.uint16)
        # Agregar ruido mínimo (vectorizado)
        noise = np.random.randint(-3, 4, depth_region.shape, dtype=np.int16)
        depth_region = (depth_region.astype(np.int16) + noise).clip(0, 65535).astype(np.uint16)

        prof = np.full((alto, ancho), 1000, dtype=np.uint16)
        prof[y:y2, x:x2] = depth_region
        self._prof_cache = prof

    def _profundidad_real(self, frame, alto, ancho):
        """Retorna la profundidad cacheada (generada por actualizar_profundidad).
        Si aún no hay cache, retorna fondo plano."""
        if self._prof_cache is not None:
            return self._prof_cache
        return np.full((alto, ancho), 1000, dtype=np.uint16)

    def _profundidad_plana(self, alto, ancho):
        ruido = np.random.randint(-2, 2, (alto, ancho))
        return (np.full((alto, ancho), 700, dtype=np.int32)
                + ruido).astype(np.uint16)

    def _profundidad_lejos(self, alto, ancho):
        return np.full((alto, ancho), 2000, dtype=np.uint16)

    def cambiar_modo(self, modo):
        self.modo = modo
        print(f"   Modo cámara: {modo}")

    def cerrar(self):
        self.webcam.release()
        print("📷 Cámara simulada cerrada")
