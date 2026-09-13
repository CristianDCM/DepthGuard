"""
Resolucion nativa de la camara y el recorte del que sale el embedding.

El bug que motiva estos tests era silencioso: la webcam se abria a 640x480 y
el pipeline solo reduce el frame `if w_orig > ANCHO_DETECCION` (640). Con la
camara a 640 esa condicion es falsa, `escala_full` se quedaba en 1.0 y
`_preparar_crop` devolvia el frame reducido. Es decir, toda la maquinaria de
"el embedding se recorta del frame nativo" existia pero NUNCA se ejecutaba,
y dlib recibia un recorte pequeno que interpolaba hasta su chip de 150x150.

Nada fallaba: el sistema reconocia, solo que con menos informacion de la que
la camara ya estaba capturando.
"""

import unittest
from unittest import mock

import numpy as np

import cv2

from motor_ia.camara.simulada import (
    CamaraSimulada, describir_fourcc, diagnosticar, FOURCC_MJPG,
)
from motor_ia.tracking import escalar_bbox


ANCHO_DETECCION = 640  # espejo de motor_ia/pipeline.py


def _decidir_escala(ancho_nativo):
    """Replica la decision del pipeline: reducir solo si supera el umbral."""
    if ancho_nativo > ANCHO_DETECCION:
        return ancho_nativo / float(ANCHO_DETECCION)
    return 1.0


class TestDescribirFourcc(unittest.TestCase):

    def test_traduce_mjpg(self):
        self.assertEqual(describir_fourcc(FOURCC_MJPG), "MJPG")

    def test_traduce_yuyv(self):
        self.assertEqual(
            describir_fourcc(cv2.VideoWriter_fourcc(*"YUYV")), "YUYV"
        )

    def test_valores_invalidos_no_revientan(self):
        # Algunos backends devuelven 0 o valores sin sentido en vez de fallar.
        for valor in (0, -1, None, "x", float("nan")):
            self.assertEqual(describir_fourcc(valor), "?")


class TestDiagnosticar(unittest.TestCase):

    def test_todo_concedido_no_avisa(self):
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=FOURCC_MJPG, fps_medido=29.4, fps_pedido=30,
        )
        self.assertEqual(avisos, [])

    def test_fps_algo_por_debajo_es_normal(self):
        # Pedir 30 y dar 24 es corriente en una webcam; no debe alarmar.
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=FOURCC_MJPG, fps_medido=24.0, fps_pedido=30,
        )
        self.assertEqual(avisos, [])

    def test_formato_sin_comprimir_que_mantiene_el_ritmo_no_avisa(self):
        # El caso real de la camara del portatil: entrega YUY2 a 1280x960 y
        # 30 FPS. La primera version avisaba de todas formas, y el aviso
        # decia "el driver baja los FPS en silencio" en la linea siguiente a
        # haber informado de 30.0 FPS: se contradecia a si mismo y mandaba al
        # usuario a arreglar algo que no estaba roto.
        #
        # De hecho es el mejor caso: convertir YUY2 a BGR cuesta 0,21 ms y
        # decodificar el JPEG de MJPG entre 5 y 14 ms (medido a 1280x960).
        # Comprimir en la camara para descomprimir en la CPU solo compensa
        # cuando el cable no da mas.
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=cv2.VideoWriter_fourcc(*"YUY2"),
            fps_medido=30.0, fps_pedido=30,
        )
        self.assertEqual(avisos, [])

    def test_detecta_desplome_de_fps(self):
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=FOURCC_MJPG, fps_medido=8.0, fps_pedido=30,
        )
        self.assertTrue(any("8.0 FPS" in a for a in avisos))

    def test_si_los_fps_caen_senala_el_formato_como_causa(self):
        # Aqui si: sin comprimir Y sin ritmo es el sintoma de un bus saturado,
        # y el aviso debe dar el numero para que se entienda por que.
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=cv2.VideoWriter_fourcc(*"YUY2"),
            fps_medido=9.0, fps_pedido=30,
        )
        texto = " ".join(avisos)
        self.assertIn("YUY2", texto)
        self.assertIn("USB 3.0", texto)
        # 1280*960*2 bytes * 30 fps = 73,7 MB/s
        self.assertIn("74 MB/s", texto)

    def test_fps_bajos_con_mjpg_no_culpan_al_formato(self):
        # Con MJPG el cuello de botella no es el ancho de banda, asi que
        # sugerir un puerto USB 3.0 seria un consejo equivocado.
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 960),
            fourcc=FOURCC_MJPG, fps_medido=7.0, fps_pedido=30,
        )
        texto = " ".join(avisos)
        self.assertNotIn("USB", texto)
        self.assertIn("cable", texto)

    def test_detecta_resolucion_no_concedida(self):
        avisos = diagnosticar(
            pedido=(1280, 960), real=(1280, 720),
            fourcc=FOURCC_MJPG, fps_medido=30.0, fps_pedido=30,
        )
        self.assertTrue(any("1280x720" in a for a in avisos))

    def test_avisa_especificamente_si_cae_a_640(self):
        # Caer a 640 no es "un poco peor": devuelve el sistema exactamente al
        # comportamiento que este cambio venia a corregir, y el aviso tiene
        # que decirlo para que no pase inadvertido.
        avisos = diagnosticar(
            pedido=(1280, 960), real=(640, 480),
            fourcc=FOURCC_MJPG, fps_medido=30.0, fps_pedido=30,
        )
        self.assertTrue(any("frame reducido" in a for a in avisos))


class _WebcamFalsa:
    """VideoCapture de mentira que entrega una resolucion a eleccion."""

    def __init__(self, ancho, alto, fourcc=FOURCC_MJPG, ancho_declarado=None):
        self.ancho = ancho
        self.alto = alto
        self.fourcc = fourcc
        # Lo que el driver DICE que entrega, que puede no ser lo que entrega.
        self.ancho_declarado = ancho_declarado or ancho

    def read(self):
        return True, np.zeros((self.alto, self.ancho, 3), dtype=np.uint8)

    def get(self, prop):
        if prop == cv2.CAP_PROP_FOURCC:
            return self.fourcc
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self.ancho_declarado
        return 0

    def set(self, prop, valor):
        return True


class TestConectar(unittest.TestCase):

    def _camara(self, webcam, pedido=(1280, 960)):
        # __new__ evita el constructor, que abriria una webcam de verdad.
        cam = CamaraSimulada.__new__(CamaraSimulada)
        cam.webcam = webcam
        cam.ancho_pedido, cam.alto_pedido = pedido
        cam.fps_pedido = 30
        cam.resolucion = None
        return cam

    def test_registra_la_resolucion_real(self):
        cam = self._camara(_WebcamFalsa(1280, 960))
        cam.conectar()
        self.assertEqual(cam.resolucion, (1280, 960))

    def test_mide_del_frame_no_de_lo_que_declara_el_driver(self):
        # Driver mentiroso: le pediste 1280 y te responde 1280 en
        # CAP_PROP_FRAME_WIDTH, pero los frames salen a 640. Si confiaramos
        # en la propiedad, el aviso no saltaria y el usuario creeria estar
        # trabajando al doble de resolucion.
        cam = self._camara(_WebcamFalsa(640, 480, ancho_declarado=1280))
        cam.conectar()
        self.assertEqual(cam.resolucion, (640, 480))

    def test_camara_muda_falla_claro(self):
        webcam = _WebcamFalsa(1280, 960)
        webcam.read = lambda: (False, None)
        cam = self._camara(webcam)
        with self.assertRaises(RuntimeError) as ctx:
            cam.conectar()
        self.assertIn("no entrega frames", str(ctx.exception))


class TestRecorteDelEmbedding(unittest.TestCase):
    """
    La regresion de verdad: cuantos pixeles reales recibe dlib.
    """

    def test_la_config_por_defecto_activa_el_recorte_nativo(self):
        # Este es el test que ata todo lo demas. Los que vienen despues
        # comprueban la aritmetica del escalado, pero la aritmetica es
        # correcta tanto a 640 como a 1280: lo que estaba mal era el VALOR
        # configurado. Si alguien devuelve CAMARA_ANCHO a 640, el resto de
        # la suite seguiria en verde y el embedding volveria a salir del
        # frame reducido en silencio. Aqui no.
        from config.settings import CAMARA_ANCHO, CAMARA_ALTO

        self.assertGreater(
            CAMARA_ANCHO, ANCHO_DETECCION,
            "Con CAMARA_ANCHO <= ANCHO_DETECCION el pipeline no reduce el "
            "frame, y el embedding vuelve a recortarse de la imagen pequena."
        )
        # 4:3 como 640x480: mantiene el encuadre del frame de deteccion y
        # con el los umbrales de calidad y liveness, que se miden ahi.
        self.assertAlmostEqual(CAMARA_ANCHO / CAMARA_ALTO, 4 / 3, places=2)

    def test_a_640_el_frame_nativo_no_se_usa(self):
        # Comportamiento anterior, documentado para que se vea el contraste.
        self.assertEqual(_decidir_escala(640), 1.0)

    def test_a_1280_la_escala_es_exactamente_2(self):
        self.assertEqual(_decidir_escala(1280), 2.0)

    def test_el_recorte_cuadruplica_los_pixeles(self):
        # Una cara a metro y medio ocupa ~90x120 px en el frame de deteccion.
        bbox_det = (275, 180, 365, 300)
        lado_det = (bbox_det[2] - bbox_det[0]) * (bbox_det[3] - bbox_det[1])

        bbox_nativo = escalar_bbox(bbox_det, _decidir_escala(1280), 1280, 960)
        lado_nativo = ((bbox_nativo[2] - bbox_nativo[0]) *
                       (bbox_nativo[3] - bbox_nativo[1]))

        # El doble de lado es el cuadruple de pixeles, y son pixeles
        # capturados, no interpolados por dlib.
        self.assertEqual(lado_nativo, lado_det * 4)

    def test_el_bbox_escalado_no_se_sale_del_frame(self):
        # Un bbox pegado al borde del frame reducido debe quedar dentro del
        # nativo: un recorte fuera de rango daria un crop vacio y dlib
        # devolveria None sin decir por que.
        bbox_det = (600, 440, 640, 480)
        x, y, x2, y2 = escalar_bbox(bbox_det, 2.0, 1280, 960)
        self.assertLessEqual(x2, 1280)
        self.assertLessEqual(y2, 960)
        self.assertGreater(x2, x)
        self.assertGreater(y2, y)


class TestPreparaCrop(unittest.TestCase):
    """`_preparar_crop` es quien decide de que imagen sale el embedding."""

    def setUp(self):
        import motor_ia.pipeline as pipeline
        self.preparar = pipeline._preparar_crop

    def test_sin_reduccion_devuelve_el_mismo_frame(self):
        reducido = np.zeros((480, 640, 3), dtype=np.uint8)
        puntos = np.array([[10.0, 20.0], [30.0, 40.0]])
        img, bbox, rgb_full, pts = self.preparar(
            reducido, (10, 10, 100, 130), None, 1.0, None, puntos
        )
        self.assertIs(img, reducido)
        self.assertEqual(bbox, (10, 10, 100, 130))
        self.assertIsNone(rgb_full)
        # Sin reduccion los landmarks ya estan en las coordenadas correctas
        self.assertIs(pts, puntos)

    def test_con_reduccion_recorta_del_nativo(self):
        reducido = np.zeros((480, 640, 3), dtype=np.uint8)
        nativo = np.zeros((960, 1280, 3), dtype=np.uint8)

        img, bbox, rgb_full, _ = self.preparar(
            reducido, (10, 10, 100, 130), nativo, 2.0, None
        )
        self.assertEqual(img.shape[:2], (960, 1280))
        self.assertEqual(bbox, (20, 20, 200, 260))
        self.assertIsNotNone(rgb_full)

    def test_los_landmarks_se_reproyectan_con_el_bbox(self):
        # El motor ONNX alinea el rostro por 5 landmarks. Si el bbox se
        # reproyecta al frame nativo pero los puntos no, la alineacion se
        # calcularia con coordenadas del frame reducido sobre una imagen del
        # doble de tamano: el rostro saldria de donde no esta.
        reducido = np.zeros((480, 640, 3), dtype=np.uint8)
        nativo = np.zeros((960, 1280, 3), dtype=np.uint8)
        puntos = np.array([[100.0, 50.0], [200.0, 75.0]])

        _, _, _, pts = self.preparar(
            reducido, (10, 10, 100, 130), nativo, 2.0, None, puntos
        )
        np.testing.assert_allclose(pts, [[200.0, 100.0], [400.0, 150.0]])
        # Y no se modifica el array original, que el pipeline sigue usando
        # para el liveness en coordenadas del frame reducido.
        np.testing.assert_allclose(puntos, [[100.0, 50.0], [200.0, 75.0]])

    def test_sin_landmarks_no_falla(self):
        # El motor dlib no los necesita, asi que el camino sin puntos existe.
        nativo = np.zeros((960, 1280, 3), dtype=np.uint8)
        _, _, _, pts = self.preparar(
            np.zeros((480, 640, 3), dtype=np.uint8),
            (10, 10, 100, 130), nativo, 2.0, None, None
        )
        self.assertIsNone(pts)

    def test_la_conversion_rgb_se_reutiliza_entre_rostros(self):
        # Convertir el frame nativo a RGB por CADA rostro del frame seria
        # pagarlo N veces. La cache se pasa de vuelta para reutilizarla.
        reducido = np.zeros((480, 640, 3), dtype=np.uint8)
        nativo = np.zeros((960, 1280, 3), dtype=np.uint8)

        _, _, cache, _ = self.preparar(
            reducido, (10, 10, 100, 130), nativo, 2.0, None
        )
        img2, _, cache2, _ = self.preparar(
            reducido, (200, 100, 300, 240), nativo, 2.0, cache
        )
        self.assertIs(cache2, cache)
        self.assertIs(img2, cache)


if __name__ == "__main__":
    unittest.main()
