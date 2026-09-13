"""Tests de los gates de calidad y de pose previos al reconocimiento."""

import sys
import os
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.validacion_calidad import (
    validar_calidad_rostro, apta_para_reconocimiento,
    pose_apta_para_reconocimiento,
    UMBRALES_REGISTRO, UMBRALES_RECONOCIMIENTO,
)


def _rostro_sintetico(lado, semilla=0):
    """Frame con ruido: nítido, bien iluminado y con contraste de sobra."""
    rng = np.random.RandomState(semilla)
    return rng.randint(40, 215, (lado, lado, 3), dtype=np.uint8)


def _frame_plano(lado, valor):
    """Frame de un solo color: sin nitidez ni contraste."""
    return np.full((lado, lado, 3), valor, dtype=np.uint8)


class TestPerfilesDeUmbrales(unittest.TestCase):

    def test_reconocimiento_es_mas_laxo_que_registro(self):
        """
        El gate de reconocimiento debe dejar pasar más que el de registro:
        rechazar un frame de reconocimiento cuesta latencia, rechazar uno de
        registro solo cuesta repetir la pose.
        """
        self.assertLess(UMBRALES_RECONOCIMIENTO.min_size, UMBRALES_REGISTRO.min_size)
        self.assertLess(UMBRALES_RECONOCIMIENTO.min_sharpness, UMBRALES_REGISTRO.min_sharpness)
        self.assertLess(UMBRALES_RECONOCIMIENTO.min_contrast, UMBRALES_REGISTRO.min_contrast)
        self.assertLess(UMBRALES_RECONOCIMIENTO.min_brightness, UMBRALES_REGISTRO.min_brightness)
        self.assertGreater(UMBRALES_RECONOCIMIENTO.max_brightness, UMBRALES_REGISTRO.max_brightness)

    def test_rostro_intermedio_pasa_reconocimiento_pero_no_registro(self):
        """
        Un rostro de 70px: demasiado pequeño para guardar una plantilla,
        suficiente para intentar identificar.
        """
        imagen = _rostro_sintetico(200)
        bbox = (0, 0, 70, 70)

        self.assertFalse(validar_calidad_rostro(imagen, bbox)[0])
        self.assertTrue(apta_para_reconocimiento(imagen, bbox)[0])


class TestGateDeCalidad(unittest.TestCase):

    def test_rostro_bueno_pasa(self):
        ok, motivo = apta_para_reconocimiento(_rostro_sintetico(200), (0, 0, 200, 200))
        self.assertTrue(ok, motivo)

    def test_rostro_diminuto_se_rechaza(self):
        ok, motivo = apta_para_reconocimiento(_rostro_sintetico(200), (0, 0, 30, 30))
        self.assertFalse(ok)
        self.assertIn("pequeño", motivo)

    def test_frame_borroso_se_rechaza(self):
        """Un frame plano no tiene bordes: varianza del Laplaciano ~ 0."""
        ok, motivo = apta_para_reconocimiento(_frame_plano(200, 128), (0, 0, 200, 200))
        self.assertFalse(ok)
        self.assertIn("borrosa", motivo)

    def test_frame_oscuro_se_rechaza(self):
        rng = np.random.RandomState(1)
        # Ruido nítido pero muy oscuro
        imagen = rng.randint(0, 20, (200, 200, 3), dtype=np.uint8)
        ok, motivo = apta_para_reconocimiento(imagen, (0, 0, 200, 200))
        self.assertFalse(ok)
        self.assertIn("oscuro", motivo)

    def test_crop_vacio_se_rechaza(self):
        """Un bbox degenerado no debe reventar el pipeline."""
        ok, _ = apta_para_reconocimiento(_rostro_sintetico(200), (100, 100, 100, 100))
        self.assertFalse(ok)

    def test_bbox_fuera_del_frame_se_rechaza_sin_excepcion(self):
        ok, _ = apta_para_reconocimiento(_rostro_sintetico(100), (90, 90, 300, 300))
        self.assertFalse(ok)


class TestGateDePose(unittest.TestCase):

    def test_frontal_pasa(self):
        ok, motivo = pose_apta_para_reconocimiento(0, 0, 35, 30)
        self.assertTrue(ok)
        self.assertEqual(motivo, "")

    def test_giro_moderado_pasa(self):
        self.assertTrue(pose_apta_para_reconocimiento(30, 20, 35, 30)[0])

    def test_giro_extremo_se_rechaza(self):
        ok, motivo = pose_apta_para_reconocimiento(50, 0, 35, 30)
        self.assertFalse(ok)
        self.assertIn("girado", motivo)

    def test_giro_extremo_hacia_el_otro_lado_tambien(self):
        """El gate es sobre el valor absoluto, no sobre el signo."""
        self.assertFalse(pose_apta_para_reconocimiento(-50, 0, 35, 30)[0])

    def test_inclinacion_extrema_se_rechaza(self):
        ok, motivo = pose_apta_para_reconocimiento(0, -45, 35, 30)
        self.assertFalse(ok)
        self.assertIn("inclinado", motivo)

    def test_limite_exacto_pasa(self):
        self.assertTrue(pose_apta_para_reconocimiento(35, 30, 35, 30)[0])


if __name__ == "__main__":
    unittest.main()
