"""
Tests de la prueba de vida 2D.

El caso que da sentido al modulo es el ultimo de este fichero: una foto
estatica ya no puede superar la verificacion.
"""

import sys
import os
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.antispoofing.liveness import (
    calcular_ear, calcular_ear_medio, analizar_textura,
    DetectorParpadeo, VerificadorLiveness,
    OJO_IZQ, OJO_DER, PENDIENTE, VIVO, FALLO,
)
from config.settings import (
    LIVENESS_FRAMES_BASE, LIVENESS_FACTOR_CIERRE,
    LIVENESS_PARPADEO_MAX_FRAMES, LIVENESS_TIMEOUT,
    LIVENESS_PARPADEOS_REQUERIDOS,
)


N_LANDMARKS = 468


def _puntos_con_ear(ear_izq, ear_der=None, ancho=30.0):
    """
    Construye landmarks sinteticos cuyo EAR es EXACTAMENTE el pedido.

    Cada ojo se dibuja como un hexagono de anchura `ancho` y altura
    ear * ancho, de modo que EAR = altura / anchura = ear.
    """
    if ear_der is None:
        ear_der = ear_izq

    puntos = np.zeros((N_LANDMARKS, 2), dtype=np.float32)

    for indices, ear, cx in ((OJO_IZQ, ear_izq, 100.0),
                             (OJO_DER, ear_der, 200.0)):
        apertura = ear * ancho
        p1, p2, p3, p4, p5, p6 = indices
        mitad = ancho / 2.0
        cy = 100.0
        puntos[p1] = (cx - mitad, cy)           # esquina externa
        puntos[p4] = (cx + mitad, cy)           # esquina interna
        # Dos pares verticales, cada uno separado exactamente `apertura`
        puntos[p2] = (cx - mitad / 2, cy - apertura / 2)
        puntos[p6] = (cx - mitad / 2, cy + apertura / 2)
        puntos[p3] = (cx + mitad / 2, cy - apertura / 2)
        puntos[p5] = (cx + mitad / 2, cy + apertura / 2)

    return puntos


class TestCalcularEAR(unittest.TestCase):

    def test_ear_es_altura_sobre_anchura(self):
        """EAR = apertura / anchura por construccion del hexagono."""
        puntos = _puntos_con_ear(0.3)
        self.assertAlmostEqual(calcular_ear(puntos, OJO_IZQ), 0.3, places=5)

    def test_ojo_cerrado_da_ear_bajo(self):
        puntos = _puntos_con_ear(0.05)
        self.assertLess(calcular_ear(puntos, OJO_IZQ), 0.1)

    def test_es_invariante_a_la_escala(self):
        """
        Acercarse a la camara no debe cambiar el EAR: por eso se normaliza
        por la anchura del ojo.
        """
        cerca = _puntos_con_ear(0.3, ancho=60.0)
        lejos = _puntos_con_ear(0.3, ancho=15.0)
        self.assertAlmostEqual(
            calcular_ear(cerca, OJO_IZQ), calcular_ear(lejos, OJO_IZQ), places=5
        )

    def test_geometria_degenerada_no_divide_por_cero(self):
        puntos = np.zeros((N_LANDMARKS, 2), dtype=np.float32)
        self.assertEqual(calcular_ear(puntos, OJO_IZQ), 0.0)

    def test_ear_medio_promedia_ambos_ojos(self):
        puntos = _puntos_con_ear(0.3, 0.1)
        self.assertAlmostEqual(calcular_ear_medio(puntos), (0.3 + 0.1) / 2, places=5)

    def test_sin_landmarks_retorna_cero(self):
        self.assertEqual(calcular_ear_medio(None), 0.0)
        self.assertEqual(calcular_ear_medio(np.zeros((10, 2))), 0.0)


class TestDetectorParpadeo(unittest.TestCase):

    def setUp(self):
        self.det = DetectorParpadeo()
        self.abierto = 0.30
        self.cerrado = self.abierto * LIVENESS_FACTOR_CIERRE * 0.5

    def _calibrar(self):
        for _ in range(LIVENESS_FRAMES_BASE):
            self.det.actualizar(self.abierto)

    def test_no_calibra_de_inmediato(self):
        self.det.actualizar(self.abierto)
        self.assertFalse(self.det.calibrado)

    def test_calibra_tras_suficientes_frames(self):
        self._calibrar()
        self.assertTrue(self.det.calibrado)
        self.assertAlmostEqual(self.det.linea_base, self.abierto, places=4)

    def test_no_cuenta_parpadeos_antes_de_calibrar(self):
        """Sin linea base no se puede decidir que es un cierre."""
        self.det.actualizar(self.cerrado)
        self.assertEqual(self.det.parpadeos, 0)

    def test_umbral_es_adaptativo_a_ojos_estrechos(self):
        """
        Alguien con EAR de 0.16 con los ojos ABIERTOS no debe contarse como
        parpadeando sin parar. Un umbral absoluto fallaria aqui.
        """
        det = DetectorParpadeo()
        abierto_estrecho = 0.16
        for _ in range(LIVENESS_FRAMES_BASE * 3):
            det.actualizar(abierto_estrecho)
        self.assertEqual(det.parpadeos, 0)
        self.assertAlmostEqual(det.linea_base, abierto_estrecho, places=4)

    def test_parpadeo_valido_se_cuenta(self):
        self._calibrar()
        self.det.actualizar(self.cerrado)      # cierra
        self.det.actualizar(self.cerrado)
        hubo = self.det.actualizar(self.abierto)  # reabre
        self.assertTrue(hubo)
        self.assertEqual(self.det.parpadeos, 1)

    def test_cierre_prolongado_no_es_parpadeo(self):
        """
        Ojos cerrados sostenidos (una foto con los ojos cerrados, o alguien
        aguantando) no es un parpadeo.
        """
        self._calibrar()
        for _ in range(LIVENESS_PARPADEO_MAX_FRAMES + 5):
            self.det.actualizar(self.cerrado)
        self.det.actualizar(self.abierto)
        self.assertEqual(self.det.parpadeos, 0)

    def test_ojos_abiertos_fijos_nunca_parpadean(self):
        """El caso de la foto impresa: EAR constante, cero parpadeos."""
        self._calibrar()
        for _ in range(200):
            self.det.actualizar(self.abierto)
        self.assertEqual(self.det.parpadeos, 0)

    def test_ruido_pequeno_no_genera_parpadeos_falsos(self):
        """La histeresis debe absorber el jitter de los landmarks."""
        self._calibrar()
        rng = np.random.RandomState(0)
        for _ in range(300):
            self.det.actualizar(self.abierto * (1 + rng.uniform(-0.08, 0.08)))
        self.assertEqual(self.det.parpadeos, 0)

    def test_varios_parpadeos_se_acumulan(self):
        self._calibrar()
        for _ in range(3):
            self.det.actualizar(self.cerrado)
            self.det.actualizar(self.abierto)
            for _ in range(5):
                self.det.actualizar(self.abierto)
        self.assertEqual(self.det.parpadeos, 3)


class TestAnalizarTextura(unittest.TestCase):

    def test_crop_pequeno_no_devuelve_metricas(self):
        """Sin pixeles suficientes no se inventa una medicion."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertEqual(analizar_textura(img, (0, 0, 16, 16)), {})

    def test_devuelve_moire_y_especular(self):
        rng = np.random.RandomState(0)
        img = rng.randint(40, 200, (200, 200, 3), dtype=np.uint8)
        m = analizar_textura(img, (0, 0, 200, 200))
        self.assertIn("moire", m)
        self.assertIn("especular", m)

    def test_rejilla_periodica_sube_el_moire(self):
        """
        Una rejilla fina (analoga al patron de pixeles de una pantalla
        fotografiada) debe dar mas energia de alta frecuencia que un degradado
        suave, que es lo que se parece mas a piel.
        """
        yy, xx = np.mgrid[0:200, 0:200]

        rejilla = (((xx % 3) < 2) * 255).astype(np.uint8)
        rejilla = np.dstack([rejilla] * 3)

        suave = ((xx + yy) / 800.0 * 255).astype(np.uint8)
        suave = np.dstack([suave] * 3)

        m_rejilla = analizar_textura(rejilla, (0, 0, 200, 200))["moire"]
        m_suave = analizar_textura(suave, (0, 0, 200, 200))["moire"]
        self.assertGreater(m_rejilla, m_suave)

    def test_reflejo_sube_el_especular(self):
        img = np.full((200, 200, 3), 100, dtype=np.uint8)
        self.assertAlmostEqual(
            analizar_textura(img, (0, 0, 200, 200))["especular"], 0.0, places=3
        )
        img[:100, :] = 255   # media imagen saturada
        self.assertGreater(
            analizar_textura(img, (0, 0, 200, 200))["especular"], 0.4
        )

    def test_bbox_fuera_del_frame_no_explota(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertIsInstance(analizar_textura(img, (80, 80, 300, 300)), dict)


class TestVerificadorLiveness(unittest.TestCase):
    """
    El test central: una foto estatica no supera la verificacion, y una
    persona que parpadea si.
    """

    def setUp(self):
        self.v = VerificadorLiveness()
        rng = np.random.RandomState(0)
        self.imagen = rng.randint(40, 200, (300, 300, 3), dtype=np.uint8)
        self.bbox = (50, 50, 250, 250)

    def _evaluar(self, det, ear, t):
        return self.v.evaluar(
            det, _puntos_con_ear(ear), self.imagen, self.bbox, t
        )

    def test_foto_estatica_nunca_supera_la_verificacion(self):
        """
        Este es el caso que antes pasaba como 'Verificado OK': el rostro de
        una foto impresa, inmovil, con los ojos siempre igual de abiertos.
        """
        det = DetectorParpadeo()
        estados = set()
        # Todo el periodo de gracia y un poco mas
        for i in range(int(LIVENESS_TIMEOUT * 20) + 40):
            estado, motivo, _ = self._evaluar(det, 0.30, i / 20.0)
            estados.add(estado)

        self.assertNotIn(VIVO, estados, "una foto estatica NO puede dar VIVO")
        self.assertIn(FALLO, estados, "pasado el timeout debe declararse FALLO")

    def test_persona_que_parpadea_supera_la_verificacion(self):
        det = DetectorParpadeo()
        t = 0.0
        paso = 1 / 20.0

        # Calibracion con ojos abiertos
        for _ in range(LIVENESS_FRAMES_BASE + 2):
            estado, _, _ = self._evaluar(det, 0.30, t)
            t += paso
        self.assertEqual(estado, PENDIENTE)

        # Parpadea
        for _ in range(2):
            self._evaluar(det, 0.08, t); t += paso
        estado, motivo, met = self._evaluar(det, 0.30, t)

        self.assertEqual(estado, VIVO, motivo)
        self.assertGreaterEqual(met["parpadeos"], LIVENESS_PARPADEOS_REQUERIDOS)

    def test_pendiente_no_es_fraude(self):
        """
        Recien llegada la persona el estado es PENDIENTE: no se concede
        acceso, pero tampoco se registra un fraude.
        """
        det = DetectorParpadeo()
        estado, _, _ = self._evaluar(det, 0.30, 0.1)
        self.assertEqual(estado, PENDIENTE)

    def test_metricas_incluyen_ear_y_textura(self):
        det = DetectorParpadeo()
        _, _, met = self._evaluar(det, 0.30, 0.1)
        for clave in ("ear", "parpadeos", "moire", "especular"):
            self.assertIn(clave, met)


if __name__ == "__main__":
    unittest.main()
