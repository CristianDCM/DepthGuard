"""
Motor de embeddings ONNX: geometria de la alineacion y guardas de seguridad.

Los tests de geometria no necesitan el modelo descargado: la alineacion es
aritmetica y es la parte que puede estar mal en silencio. Si un rostro se
alinea mal, el sistema no falla —sigue produciendo un vector de 512 numeros—
solo reconoce peor, y eso no se nota hasta que alguien no puede entrar.

Los que si necesitan el modelo se saltan solos si no esta descargado.
"""

import os
import unittest

import numpy as np

from motor_ia.reconocimiento.motor_onnx import (
    similaridad, cinco_puntos, alinear, alinear_por_bbox, preprocesar,
    PLANTILLA_ARCFACE, LADO_ENTRADA,
    OJO_IZQ, OJO_DER, _LM_NARIZ, _LM_BOCA_A, _LM_BOCA_B,
)
from config.settings import RUTA_MODELO_ONNX


def _puntos(cx=320.0, cy=240.0, esc=1.0, invertir=False):
    """468 landmarks con los 5 relevantes puestos como una cara de frente."""
    p = np.zeros((468, 2))
    izq = (cx + 45 * esc, cy - 30 * esc) if invertir else (cx - 45 * esc, cy - 30 * esc)
    der = (cx - 45 * esc, cy - 30 * esc) if invertir else (cx + 45 * esc, cy - 30 * esc)
    for i in OJO_IZQ:
        p[i] = izq
    for i in OJO_DER:
        p[i] = der
    p[_LM_NARIZ] = (cx, cy)
    p[_LM_BOCA_A] = (cx - 35 * esc, cy + 45 * esc)
    p[_LM_BOCA_B] = (cx + 35 * esc, cy + 45 * esc)
    return p


class TestSimilaridad(unittest.TestCase):

    def test_recupera_una_transformacion_conocida(self):
        ang = np.deg2rad(23.0)
        escala = 1.7
        traslacion = np.array([40.0, -15.0])
        rot = np.array([[np.cos(ang), -np.sin(ang)],
                        [np.sin(ang), np.cos(ang)]])
        origen = np.array([[10., 10.], [50., 12.], [30., 35.],
                           [15., 55.], [45., 54.]])
        destino = (escala * (rot @ origen.T)).T + traslacion

        m = similaridad(origen, destino)
        reconstruido = (m[:, :2] @ origen.T).T + m[:, 2]
        np.testing.assert_allclose(reconstruido, destino, atol=1e-9)
        self.assertAlmostEqual(np.sqrt(np.linalg.det(m[:, :2])), escala, places=6)

    def test_identidad_si_origen_es_igual_a_destino(self):
        m = similaridad(PLANTILLA_ARCFACE, PLANTILLA_ARCFACE)
        np.testing.assert_allclose(m, [[1, 0, 0], [0, 1, 0]], atol=1e-9)

    def test_nunca_refleja(self):
        # Una semejanza no incluye reflexiones. Si la SVD cuela una, el rostro
        # se alinearia espejado y el modelo veria una cara que no es la que hay.
        origen = np.array([[10., 10.], [50., 12.], [30., 35.],
                           [15., 55.], [45., 54.]])
        espejo = origen.copy()
        espejo[:, 0] = -espejo[:, 0]
        m = similaridad(espejo, origen)
        self.assertGreater(np.linalg.det(m[:, :2]), 0)

    def test_puntos_degenerados_no_revientan(self):
        # Todos los landmarks en el mismo sitio: no debe lanzar excepcion.
        iguales = np.tile([100.0, 100.0], (5, 1))
        m = similaridad(iguales, PLANTILLA_ARCFACE)
        self.assertEqual(m.shape, (2, 3))
        self.assertTrue(np.all(np.isfinite(m)))


class TestCincoPuntos(unittest.TestCase):

    def test_ordena_los_ojos_por_x(self):
        p5 = cinco_puntos(_puntos())
        self.assertLess(p5[0][0], p5[1][0])

    def test_ordena_igual_si_los_indices_vienen_al_reves(self):
        # Que indice de MediaPipe cae a que lado depende de si la imagen esta
        # espejada. Equivocarse intercambia los dos ojos, y entonces la
        # transformacion gira el rostro 180 grados: el embedding saldria de una
        # cara del reves. Ordenar por x lo hace correcto en ambos casos.
        normal = cinco_puntos(_puntos(invertir=False))
        invertido = cinco_puntos(_puntos(invertir=True))
        np.testing.assert_allclose(normal, invertido)

    def test_ordena_la_boca_por_x(self):
        p5 = cinco_puntos(_puntos())
        self.assertLess(p5[3][0], p5[4][0])

    def test_la_nariz_va_en_medio(self):
        p5 = cinco_puntos(_puntos())
        self.assertAlmostEqual(p5[2][0], 320.0)


class TestAlinear(unittest.TestCase):

    def test_devuelve_el_tamano_que_espera_el_modelo(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        salida = alinear(img, _puntos())
        self.assertEqual(salida.shape, (LADO_ENTRADA, LADO_ENTRADA, 3))
        self.assertEqual(salida.dtype, np.uint8)

    def test_lleva_los_cinco_puntos_cerca_de_la_plantilla(self):
        # Una semejanza tiene 4 grados de libertad y no puede clavar 5 puntos:
        # es minimos cuadrados. Pero un error de pocos pixeles significa que la
        # alineacion esta haciendo su trabajo; decenas significaria que no.
        p = _puntos()
        m = similaridad(cinco_puntos(p), PLANTILLA_ARCFACE)
        proyectados = (m[:, :2] @ cinco_puntos(p).T).T + m[:, 2]
        errores = np.linalg.norm(proyectados - PLANTILLA_ARCFACE, axis=1)
        self.assertLess(errores.max(), 5.0)

    def test_invariante_a_la_escala_del_rostro(self):
        # Una cara lejana y una cercana deben alinearse a la MISMA imagen: es
        # justo lo que aporta la alineacion frente a reescalar el bbox.
        img = np.zeros((960, 1280, 3), dtype=np.uint8)
        cerca = similaridad(cinco_puntos(_puntos(640, 480, 2.0)), PLANTILLA_ARCFACE)
        lejos = similaridad(cinco_puntos(_puntos(640, 480, 1.0)), PLANTILLA_ARCFACE)
        # Misma geometria de destino aunque la escala de origen sea el doble
        p_cerca = (cerca[:, :2] @ cinco_puntos(_puntos(640, 480, 2.0)).T).T + cerca[:, 2]
        p_lejos = (lejos[:, :2] @ cinco_puntos(_puntos(640, 480, 1.0)).T).T + lejos[:, 2]
        np.testing.assert_allclose(p_cerca, p_lejos, atol=1e-6)

    def test_alineacion_de_emergencia_con_bbox_fuera_de_rango(self):
        # Un bbox degenerado no debe petar: devuelve una imagen del tamano
        # correcto para que el motor siga funcionando.
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        salida = alinear_por_bbox(img, (90, 90, 80, 80))
        self.assertEqual(salida.shape, (LADO_ENTRADA, LADO_ENTRADA, 3))


class TestPreprocesar(unittest.TestCase):

    def test_normaliza_a_menos_uno_uno_y_pasa_a_canales_primero(self):
        img = np.full((112, 112, 3), 127.5, dtype=np.uint8)
        t = preprocesar(img)
        self.assertEqual(t.shape, (3, 112, 112))
        self.assertEqual(t.dtype, np.float32)
        self.assertLess(abs(float(t.mean())), 0.01)

    def test_extremos(self):
        np.testing.assert_allclose(preprocesar(np.zeros((112, 112, 3), np.uint8)), -1.0)
        t = preprocesar(np.full((112, 112, 3), 255, np.uint8))
        np.testing.assert_allclose(t, 1.0, atol=1e-6)


@unittest.skipUnless(os.path.isfile(RUTA_MODELO_ONNX),
                     "modelo no descargado (python scripts/descargar_modelo.py)")
class TestMotorConModelo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from motor_ia.reconocimiento.motor_onnx import MotorONNX
        cls.motor = MotorONNX(RUTA_MODELO_ONNX)
        cls.img = np.random.RandomState(5).randint(
            40, 220, (960, 1280, 3), dtype=np.uint8)

    def test_devuelve_vector_normalizado(self):
        v = self.motor.generar(self.img, (500, 300, 700, 560), _puntos(600, 430))
        self.assertEqual(v.shape, (512,))
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)

    def test_es_determinista(self):
        a = self.motor.generar(self.img, (500, 300, 700, 560), _puntos(600, 430))
        b = self.motor.generar(self.img, (500, 300, 700, 560), _puntos(600, 430))
        np.testing.assert_array_equal(a, b)

    def test_el_lote_da_lo_mismo_que_las_llamadas_sueltas(self):
        # Si el lote difiriera, la identidad de una persona dependeria de
        # cuanta gente mas hay en el frame.
        rostros = [((500, 300, 700, 560), _puntos(600, 430)),
                   ((200, 200, 380, 440), _puntos(290, 320, 0.9))]
        lote = self.motor.generar_lote(self.img, rostros)
        sueltos = np.stack([self.motor.generar(self.img, b, p) for b, p in rostros])
        np.testing.assert_allclose(lote, sueltos, atol=0)

    def test_lote_vacio(self):
        self.assertEqual(len(self.motor.generar_lote(self.img, [])), 0)

    def test_sin_landmarks_sigue_funcionando(self):
        v = self.motor.generar(self.img, (500, 300, 700, 560), None)
        self.assertEqual(v.shape, (512,))
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)


class TestGuardaDeIncompatibilidad(unittest.TestCase):
    """
    Mezclar plantillas de los dos motores no debe compararse NUNCA.

    128D y 512D son espacios distintos e incomparables. Restarlos o revienta o
    hace broadcast y devuelve numeros sin significado, y el sistema concederia
    o denegaria accesos por aritmetica basura.
    """

    def test_descarta_las_plantillas_de_otra_dimension(self):
        from motor_ia.reconocimiento import embedding_generator as eg

        rec = eg.ReconocedorFacial()
        esperadas = eg._DIMENSIONES
        otras = 512 if esperadas == 128 else 128

        rec.cargar_cache([
            {"id": "1", "nombre": "Buena",
             "embeddings": [np.zeros(esperadas).tolist()]},
            {"id": "2", "nombre": "DeOtroMotor",
             "embeddings": [np.zeros(otras).tolist()]},
        ])

        self.assertEqual(len(rec.cache), 1)
        self.assertEqual(rec._matriz.shape, (1, esperadas))
        self.assertEqual([n for _, n in rec._identidades], ["Buena", "DeOtroMotor"])

    def test_si_todas_son_incompatibles_no_reconoce_a_nadie(self):
        from motor_ia.reconocimiento import embedding_generator as eg

        rec = eg.ReconocedorFacial()
        otras = 512 if eg._DIMENSIONES == 128 else 128
        rec.cargar_cache([
            {"id": "1", "nombre": "X", "embeddings": [np.zeros(otras).tolist()]},
        ])
        self.assertEqual(len(rec.cache), 0)
        # Y buscar no revienta: simplemente no identifica
        nombre, conf, uid = rec.buscar(np.zeros(eg._DIMENSIONES))
        self.assertIsNone(nombre)
        self.assertIsNone(uid)


class TestMotorPorDefecto(unittest.TestCase):

    def test_el_defecto_sigue_siendo_dlib(self):
        # Cambiar el motor invalida todas las plantillas guardadas. Si el
        # defecto fuera onnx, un `git pull` dejaria el sistema sin reconocer a
        # nadie sin que nadie lo hubiera pedido.
        import re
        with open("config/settings.py", encoding="utf-8") as f:
            fuente = f.read()
        m = re.search(r'MOTOR_EMBEDDING = _env\.get\("MOTOR_EMBEDDING", "(\w+)"\)',
                      fuente)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "dlib")


if __name__ == "__main__":
    unittest.main()
