"""Tests para el módulo anti-spoofing."""

import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.antispoofing.verificador_3d import VerificadorAntiSpoofing


class TestAntiSpoofing(unittest.TestCase):

    def setUp(self):
        self.verificador = VerificadorAntiSpoofing()
        self.bbox = (100, 100, 300, 300)

    def test_superficie_plana_detectada_como_fraude(self):
        """Un mapa sin variación 3D debe ser fraude."""
        # 700 / 10 = 70cm → dentro del rango 25-150cm
        # Pero varianza ~0 → superficie plana → fraude
        ruido = np.random.randint(-2, 2, (480, 640))
        mapa = (np.full((480, 640), 700, dtype=np.int32) + ruido).astype(np.uint16)
        es_real, es_dist, motivo, metricas = self.verificador.verificar(
            mapa, self.bbox
        )
        self.assertFalse(es_real)
        self.assertFalse(es_dist)

    def test_rostro_real_con_profundidad(self):
        """Un mapa con curvatura 3D realista debe pasar."""
        # Base 670 / 10 = 67cm → dentro del rango
        mapa = np.full((480, 640), 1000, dtype=np.uint16)
        cx, cy = 200, 200
        for y in range(100, 300):
            for x in range(100, 300):
                dy = abs(y - cy) / 100.0
                dx = abs(x - cx) / 100.0
                # Curvatura fuerte: base 670 + hasta ~600
                mapa[y, x] = int(670 + (dx**2 + dy**2) * 600
                                 + np.random.randint(-30, 30))
        es_real, es_dist, motivo, metricas = self.verificador.verificar(
            mapa, self.bbox
        )
        self.assertTrue(es_real)

    def test_campos_metricas_usan_nombres_correctos(self):
        """Las métricas deben usar rango_3d y pixeles_validos (no rango/pixeles)."""
        mapa = np.full((480, 640), 1000, dtype=np.uint16)
        cx, cy = 200, 200
        for y in range(100, 300):
            for x in range(100, 300):
                dy = abs(y - cy) / 100.0
                dx = abs(x - cx) / 100.0
                mapa[y, x] = int(670 + (dx**2 + dy**2) * 600
                                 + np.random.randint(-30, 30))
        _, _, _, metricas = self.verificador.verificar(mapa, self.bbox)
        # Campos esperados por el frontend
        self.assertIn("varianza", metricas)
        self.assertIn("distancia", metricas)
        self.assertIn("rango_3d", metricas)
        self.assertIn("pixeles_validos", metricas)
        # Campos legacy NO deben existir
        self.assertNotIn("rango", metricas)
        self.assertNotIn("pixeles", metricas)

    def test_pixeles_validos_normalizado_0_1(self):
        """pixeles_validos debe estar en escala 0.0-1.0 (el frontend multiplica por 100)."""
        mapa = np.full((480, 640), 700, dtype=np.uint16)
        for y in range(100, 300):
            for x in range(100, 300):
                mapa[y, x] = 700 + np.random.randint(-5, 5)
        _, _, _, metricas = self.verificador.verificar(mapa, self.bbox)
        if "pixeles_validos" in metricas:
            self.assertGreaterEqual(metricas["pixeles_validos"], 0.0)
            self.assertLessEqual(metricas["pixeles_validos"], 1.0)

    def test_distancia_muy_lejos(self):
        """Una persona muy lejos debe marcarse como distancia."""
        # 20000 / 10 = 2000cm → muy lejos, fuera del rango 25-150cm
        mapa = np.full((480, 640), 20000, dtype=np.uint16)
        for y in range(100, 300):
            for x in range(100, 300):
                mapa[y, x] = 20000 + np.random.randint(-100, 100)
        es_real, es_dist, motivo, metricas = self.verificador.verificar(
            mapa, self.bbox
        )
        self.assertFalse(es_real)
        self.assertTrue(es_dist)

    def test_sin_datos_de_profundidad(self):
        """Sin datos de profundidad debe retornar fraude."""
        mapa = np.zeros((480, 640), dtype=np.uint16)
        es_real, es_dist, motivo, metricas = self.verificador.verificar(
            mapa, self.bbox
        )
        self.assertFalse(es_real)


class TestBBox(unittest.TestCase):

    def setUp(self):
        self.verificador = VerificadorAntiSpoofing()

    def test_bbox_en_bordes_no_crashea(self):
        """Bounding box en los bordes de la imagen no debe crashear."""
        mapa = np.full((480, 640), 7000, dtype=np.uint16)
        bbox_borde = (0, 0, 100, 100)
        es_real, es_dist, motivo, metricas = self.verificador.verificar(
            mapa, bbox_borde
        )
        # Solo verificar que no crashea
        self.assertIsInstance(es_real, bool)


if __name__ == "__main__":
    unittest.main()
