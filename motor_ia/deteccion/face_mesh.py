"""Detección facial con MediaPipe Face Mesh (multi-ángulo)."""

import mediapipe as mp


class DetectorFaceMesh:

    def __init__(self):
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.4,
            min_tracking_confidence=0.4
        )
        self.INDICES_BBOX = [10, 152, 234, 454, 1, 33, 263, 61, 291]

    def detectar(self, imagen_rgb):
        """
        Retorna (encontrada, bbox, angulo, direccion).
        bbox = (x, y, x2, y2) o None
        """
        alto, ancho = imagen_rgb.shape[:2]
        # Optimización oficial MediaPipe: evita copia interna del array
        imagen_rgb.flags.writeable = False
        resultado = self.face_mesh.process(imagen_rgb)
        imagen_rgb.flags.writeable = True

        if not resultado.multi_face_landmarks:
            return False, None, 0, "ninguno"

        landmarks = resultado.multi_face_landmarks[0]
        bbox = self._calcular_bbox(landmarks, ancho, alto)
        angulo, direccion = self._calcular_angulo(landmarks, ancho, alto)

        return True, bbox, angulo, direccion

    def _calcular_bbox(self, landmarks, ancho, alto):
        xs = []
        ys = []

        for i in self.INDICES_BBOX:
            lm = landmarks.landmark[i]
            xs.append(int(lm.x * ancho))
            ys.append(int(lm.y * alto))

        margen = 25
        return (
            max(0, min(xs) - margen),
            max(0, min(ys) - margen),
            min(ancho, max(xs) + margen),
            min(alto, max(ys) + margen)
        )

    def _calcular_angulo(self, landmarks, ancho, alto):
        nariz_x = landmarks.landmark[1].x * ancho
        ojo_izq_x = landmarks.landmark[33].x * ancho
        ojo_der_x = landmarks.landmark[263].x * ancho

        centro = (ojo_izq_x + ojo_der_x) / 2
        dist_ojos = abs(ojo_der_x - ojo_izq_x)

        if dist_ojos < 1:
            return 0, "frontal"

        despl = (nariz_x - centro) / dist_ojos
        angulo = round(despl * 60, 1)

        if angulo < -10:
            return angulo, "derecha"
        elif angulo > 10:
            return angulo, "izquierda"
        return angulo, "frontal"

    def cerrar(self):
        self.face_mesh.close()
