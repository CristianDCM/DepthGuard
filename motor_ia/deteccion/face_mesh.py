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
        direccion puede ser: "frontal", "izquierda", "derecha", "arriba", "abajo"
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
        angulo_h, angulo_v, direccion = self._calcular_angulo(landmarks, ancho, alto)

        return True, bbox, angulo_h, direccion

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
        """
        Calcula ángulo horizontal y vertical del rostro.
        Retorna (angulo_horizontal, angulo_vertical, direccion).
        
        Direcciones posibles: "frontal", "izquierda", "derecha", "arriba", "abajo"
        """
        # === Ángulo horizontal (yaw) ===
        nariz_x = landmarks.landmark[1].x * ancho
        ojo_izq_x = landmarks.landmark[33].x * ancho
        ojo_der_x = landmarks.landmark[263].x * ancho

        centro_x = (ojo_izq_x + ojo_der_x) / 2
        dist_ojos = abs(ojo_der_x - ojo_izq_x)

        if dist_ojos < 1:
            return 0, 0, "frontal"

        despl_h = (nariz_x - centro_x) / dist_ojos
        angulo_h = round(despl_h * 60, 1)

        # === Ángulo vertical (pitch) ===
        # Punto medio entre los ojos (Y)
        ojo_izq_y = landmarks.landmark[33].y * alto
        ojo_der_y = landmarks.landmark[263].y * alto
        centro_ojos_y = (ojo_izq_y + ojo_der_y) / 2

        # Punta de la nariz (landmark 1) y mentón (landmark 152)
        nariz_y = landmarks.landmark[1].y * alto
        menton_y = landmarks.landmark[152].y * alto

        # Distancia vertical entre ojos y mentón como referencia
        dist_vertical = abs(menton_y - centro_ojos_y)

        if dist_vertical < 1:
            return angulo_h, 0, "frontal"

        # Posición relativa de la nariz entre ojos y mentón
        # Si la nariz está más arriba (cabeza mirando hacia arriba), despl_v es negativo
        # Si la nariz está más abajo (cabeza mirando hacia abajo), despl_v es positivo
        ratio_nariz = (nariz_y - centro_ojos_y) / dist_vertical
        # Valor esperado ~0.4-0.5 cuando el rostro es frontal
        despl_v = (ratio_nariz - 0.45) * 100
        angulo_v = round(despl_v, 1)

        # Determinar dirección predominante
        # El vertical tiene prioridad menor; solo se reporta si el horizontal es frontal
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

    def cerrar(self):
        self.face_mesh.close()
