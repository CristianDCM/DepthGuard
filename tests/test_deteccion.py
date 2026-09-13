"""Tests del cálculo de bbox y ángulos a partir de landmarks."""

import sys
import os
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.deteccion.face_mesh import calcular_bbox, calcular_angulo, MARGEN_REL


def _malla_sintetica(cx, cy, lado, n=468):
    """
    Genera una nube de landmarks cuadrada de `lado` px centrada en (cx, cy),
    con los índices usados para los ángulos colocados en posición frontal.
    """
    puntos = np.zeros((n, 2), dtype=np.float32)

    # Nube que llena exactamente el cuadrado [cx±lado/2, cy±lado/2]
    mitad = lado / 2.0
    rng = np.random.RandomState(0)
    puntos[:, 0] = cx + rng.uniform(-mitad, mitad, n)
    puntos[:, 1] = cy + rng.uniform(-mitad, mitad, n)

    # Fijar las esquinas para que la envolvente sea exacta
    puntos[0] = (cx - mitad, cy - mitad)
    puntos[2] = (cx + mitad, cy + mitad)

    # Landmarks de ángulo en configuración frontal:
    # nariz centrada entre los ojos, y al 45% entre ojos y mentón
    puntos[33] = (cx - lado * 0.2, cy - lado * 0.1)   # ojo izq
    puntos[263] = (cx + lado * 0.2, cy - lado * 0.1)  # ojo der
    puntos[152] = (cx, cy + mitad)                     # mentón
    centro_ojos_y = cy - lado * 0.1
    dist_v = abs(puntos[152][1] - centro_ojos_y)
    puntos[1] = (cx, centro_ojos_y + 0.45 * dist_v)    # nariz

    return puntos


class TestCalcularBbox(unittest.TestCase):

    def test_margen_es_proporcional_al_tamano(self):
        """
        El margen debe escalar con el rostro: dos rostros de tamaños
        distintos deben producir crops con la MISMA escala relativa.

        Esto es lo que el margen fijo de 25px no hacía, y es lo que
        desestabilizaba los embeddings según la distancia a la cámara.
        """
        grande = calcular_bbox(_malla_sintetica(300, 300, 200), 640, 480)
        pequeno = calcular_bbox(_malla_sintetica(300, 300, 80), 640, 480)

        # Razón entre el lado del bbox y el lado del rostro
        razon_grande = (grande[2] - grande[0]) / 200.0
        razon_pequeno = (pequeno[2] - pequeno[0]) / 80.0

        self.assertAlmostEqual(razon_grande, razon_pequeno, delta=0.03)
        # Y ambas deben rondar 1 + 2*MARGEN_REL
        self.assertAlmostEqual(razon_grande, 1 + 2 * MARGEN_REL, delta=0.03)

    def test_bbox_usa_la_envolvente_completa(self):
        """El bbox debe contener todos los landmarks."""
        puntos = _malla_sintetica(320, 240, 150)
        x, y, x2, y2 = calcular_bbox(puntos, 640, 480)

        self.assertLessEqual(x, puntos[:, 0].min())
        self.assertLessEqual(y, puntos[:, 1].min())
        self.assertGreaterEqual(x2, puntos[:, 0].max())
        self.assertGreaterEqual(y2, puntos[:, 1].max())

    def test_bbox_no_sale_del_frame(self):
        """Un rostro pegado al borde no debe generar coordenadas negativas."""
        puntos = _malla_sintetica(20, 15, 100)
        x, y, x2, y2 = calcular_bbox(puntos, 640, 480)

        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x2, 640)
        self.assertLessEqual(y2, 480)

    def test_bbox_no_depende_de_landmarks_individuales(self):
        """
        Mover un landmark interior no debe cambiar el bbox (a diferencia del
        cálculo anterior, que dependía de 9 puntos concretos).
        """
        puntos = _malla_sintetica(320, 240, 150)
        base = calcular_bbox(puntos, 640, 480)

        # Mover la nariz dentro de la nube: no es extremo, no cambia nada
        puntos[1] = (320, 250)
        self.assertEqual(calcular_bbox(puntos, 640, 480), base)


class TestCalcularAngulo(unittest.TestCase):

    def test_rostro_frontal(self):
        angulo_h, angulo_v, direccion = calcular_angulo(_malla_sintetica(320, 240, 150))
        self.assertEqual(direccion, "frontal")
        self.assertAlmostEqual(angulo_h, 0.0, delta=1.0)
        self.assertAlmostEqual(angulo_v, 0.0, delta=1.0)

    def test_nariz_desplazada_da_giro(self):
        """Desplazar la nariz hacia un lado debe reportar giro, no frontal."""
        puntos = _malla_sintetica(320, 240, 150)
        puntos[1] = (puntos[1][0] + 20, puntos[1][1])
        angulo_h, _, direccion = calcular_angulo(puntos)

        self.assertGreater(angulo_h, 10)
        self.assertEqual(direccion, "izquierda")

    def test_pitch_se_devuelve_y_no_se_pierde(self):
        """
        angulo_v debe llegar al llamante. Antes se calculaba y se descartaba
        al construir la tupla de resultado del detector.
        """
        puntos = _malla_sintetica(320, 240, 150)
        # Subir la nariz hacia los ojos -> mirando arriba
        centro_ojos_y = puntos[33][1]
        puntos[1] = (puntos[1][0], centro_ojos_y + 0.20 * abs(puntos[152][1] - centro_ojos_y))

        angulo_h, angulo_v, direccion = calcular_angulo(puntos)
        self.assertLess(angulo_v, -8)
        self.assertEqual(direccion, "arriba")

    def test_ojos_degenerados_no_explotan(self):
        """Ojos en el mismo punto (dist_ojos ~ 0) no debe dividir por cero."""
        puntos = _malla_sintetica(320, 240, 150)
        puntos[33] = puntos[263] = (320, 230)
        angulo_h, angulo_v, direccion = calcular_angulo(puntos)
        self.assertEqual((angulo_h, angulo_v, direccion), (0.0, 0.0, "frontal"))


if __name__ == "__main__":
    unittest.main()
