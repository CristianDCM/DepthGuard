"""Cámara simulada usando webcam + profundidad artificial."""

import cv2
import numpy as np
import mediapipe as mp


class CamaraSimulada:

    def __init__(self):
        self.webcam = cv2.VideoCapture(0)
        if not self.webcam.isOpened():
            raise RuntimeError("No se detectó webcam")

        self.detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5
        )
        self.modo = "REAL"

    def conectar(self):
        print("✅ Cámara SIMULADA conectada (webcam)")

    def obtener_frames(self):
        ret, frame = self.webcam.read()
        if not ret:
            return None, None

        alto, ancho = frame.shape[:2]

        if self.modo == "REAL":
            prof = self._profundidad_real(frame, alto, ancho)
        elif self.modo == "FRAUDE":
            prof = self._profundidad_plana(alto, ancho)
        else:
            prof = self._profundidad_lejos(alto, ancho)

        return frame, prof

    def _profundidad_real(self, frame, alto, ancho):
        prof = np.full((alto, ancho), 1000, dtype=np.uint16)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.detector.process(rgb)

        if res.detections:
            for det in res.detections:
                bbox = det.location_data.relative_bounding_box
                x = max(0, int(bbox.xmin * ancho))
                y = max(0, int(bbox.ymin * alto))
                w = int(bbox.width * ancho)
                h = int(bbox.height * alto)
                cx, cy = x + w // 2, y + h // 2

                for py in range(y, min(alto, y + h)):
                    for px in range(x, min(ancho, x + w)):
                        dy = abs(py - cy) / max(h / 2, 1)
                        dx = abs(px - cx) / max(w / 2, 1)
                        prof[py, px] = int(
                            670 + (dx**2 + dy**2) * 60
                            + np.random.randint(-3, 3)
                        )
        return prof

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
        self.detector.close()
        self.webcam.release()
        print("📷 Cámara simulada cerrada")
