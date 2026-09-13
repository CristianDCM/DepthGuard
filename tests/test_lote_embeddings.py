"""
Generacion de embeddings por lote: reparto, presupuesto y ORDEN.

El riesgo que justifica la mayoria de estos tests no es de rendimiento. Al
agrupar N rostros en una sola inferencia, los resultados vuelven como una
lista, y si se reparten mal el embedding de una persona se atribuye a OTRA: el
sistema identificaria a alguien como quien no es y le concederia el acceso.
Un fallo de ese tipo no se nota mirando si "funciona" —siempre devuelve un
nombre— asi que tiene que estar cubierto.
"""

import unittest

import numpy as np

import motor_ia.pipeline as pipeline
from motor_ia.deteccion.face_mesh import RostroDetectado
from motor_ia.tracking import PersonaTrack


def _rostro(x, y=100, lado=120, direccion="frontal", yaw=0.0, pitch=0.0):
    """Rostro detectado con un bbox identificable por su x."""
    puntos = np.zeros((468, 2), dtype=np.float32)
    puntos[:] = (x + lado / 2, y + lado / 2)
    return RostroDetectado((x, y, x + lado, y + lado), yaw, pitch, direccion, puntos)


class _ReconocedorFalso:
    """
    Devuelve un vector que CODIFICA el bbox que recibio, para poder comprobar
    despues que cada embedding acabo en el rostro correcto.
    """

    def __init__(self, fallar_en=()):
        self.llamadas = []          # lista de listas de bbox por llamada
        self.fallar_en = set(fallar_en)

    def generar_lote(self, imagen_rgb, rostros):
        self.llamadas.append([bbox for bbox, _ in rostros])
        salida = []
        for bbox, _ in rostros:
            if bbox[0] in self.fallar_en:
                salida.append(None)
            else:
                v = np.zeros(8)
                v[0] = bbox[0]      # la x identifica al rostro
                salida.append(v)
        return salida


class _Calidad:
    """Gate de calidad configurable por coordenada x del bbox."""

    def __init__(self, rechazar_x=()):
        self.rechazar_x = set(rechazar_x)

    def __call__(self, imagen_rgb, bbox):
        if bbox[0] in self.rechazar_x:
            return False, "borroso"
        return True, "OK"


class BaseLote(unittest.TestCase):

    def setUp(self):
        self.imagen = np.zeros((480, 640, 3), dtype=np.uint8)
        self._calidad_orig = pipeline.apta_para_reconocimiento
        self._pose_orig = pipeline.pose_apta_para_reconocimiento
        pipeline.apta_para_reconocimiento = _Calidad()
        pipeline.pose_apta_para_reconocimiento = lambda *a, **k: (True, "")

    def tearDown(self):
        pipeline.apta_para_reconocimiento = self._calidad_orig
        pipeline.pose_apta_para_reconocimiento = self._pose_orig

    def planificar(self, matched, rec, ahora=1000.0, presupuesto=5,
                   escala=1.0, nativo=None):
        return pipeline._planificar_embeddings(
            matched, ahora, rec, self.imagen, nativo, escala, None, presupuesto
        )


class TestUnaSolaInferencia(BaseLote):

    def test_tres_rostros_van_en_una_sola_llamada(self):
        # Es el objetivo del cambio: sin esto, cada rostro seria una inferencia
        # y un grupo tardaria varios frames en identificarse.
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(10)), (None, _rostro(200)), (None, _rostro(400))]
        decisiones, _ = self.planificar(matched, rec)

        self.assertEqual(len(rec.llamadas), 1)
        self.assertEqual(len(rec.llamadas[0]), 3)
        self.assertTrue(all(d is not None for d in decisiones))

    def test_sin_candidatos_no_llama_al_motor(self):
        rec = _ReconocedorFalso()
        t = PersonaTrack((10, 10, 50, 50), 0.0, "frontal")
        t.t_proximo_embedding = 2000.0     # aun en cooldown
        decisiones, _ = self.planificar([(t, _rostro(10))], rec, ahora=1000.0)
        self.assertEqual(rec.llamadas, [])
        self.assertIsNone(decisiones[0])


class TestRepartoCorrecto(BaseLote):
    """La parte que puede confundir a dos personas."""

    def test_cada_embedding_va_a_su_rostro(self):
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(10)), (None, _rostro(200)), (None, _rostro(400))]
        decisiones, _ = self.planificar(matched, rec)

        for (_, rostro), decision in zip(matched, decisiones):
            # El vector codifica la x del bbox del que salio.
            self.assertEqual(decision.embedding[0], rostro.bbox[0])

    def test_el_reparto_aguanta_que_haya_huecos(self):
        # Con rostros descartados por el gate en medio, los indices del lote y
        # los de `matched` dejan de coincidir. Es exactamente donde un reparto
        # por posicion se equivoca y cruza identidades.
        pipeline.apta_para_reconocimiento = _Calidad(rechazar_x=(200,))
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(10)), (None, _rostro(200)), (None, _rostro(400))]
        decisiones, _ = self.planificar(matched, rec)

        # El rechazado no entra en el lote
        self.assertEqual(rec.llamadas[0], [(10, 100, 130, 220), (400, 100, 520, 220)])
        self.assertEqual(decisiones[0].embedding[0], 10)
        self.assertEqual(decisiones[1].embedding, None)
        self.assertEqual(decisiones[1].motivo_gate, "borroso")
        self.assertEqual(decisiones[2].embedding[0], 400)

    def test_el_reparto_aguanta_un_hueco_en_medio_del_lote(self):
        # Y si el motor devuelve None para uno del lote, los demas no se
        # desplazan.
        rec = _ReconocedorFalso(fallar_en=(200,))
        matched = [(None, _rostro(10)), (None, _rostro(200)), (None, _rostro(400))]
        decisiones, _ = self.planificar(matched, rec)
        self.assertEqual(decisiones[0].embedding[0], 10)
        self.assertIsNone(decisiones[1].embedding)
        self.assertEqual(decisiones[2].embedding[0], 400)


class TestPresupuesto(BaseLote):

    def test_respeta_el_tope_por_frame(self):
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(x)) for x in (10, 120, 240, 360, 480)]
        decisiones, _ = self.planificar(matched, rec, presupuesto=2)

        self.assertEqual(len(rec.llamadas[0]), 2)
        self.assertEqual(sum(1 for d in decisiones if d is not None), 2)

    def test_respeta_el_orden_de_prioridad(self):
        # `matched` llega ya ordenado por prioridad, asi que el presupuesto debe
        # gastarse en los PRIMEROS. Si se gastara en otros, alguien que acaba de
        # entrar podria quedarse sin identificar mientras se re-confirma a quien
        # ya se conoce.
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(10)), (None, _rostro(200)), (None, _rostro(400))]
        decisiones, _ = self.planificar(matched, rec, presupuesto=1)

        self.assertEqual(rec.llamadas[0], [(10, 100, 130, 220)])
        self.assertIsNotNone(decisiones[0])
        self.assertIsNone(decisiones[1])
        self.assertIsNone(decisiones[2])

    def test_presupuesto_cero_no_genera_nada(self):
        rec = _ReconocedorFalso()
        decisiones, _ = self.planificar([(None, _rostro(10))], rec, presupuesto=0)
        self.assertEqual(rec.llamadas, [])
        self.assertEqual(decisiones, [None])

    def test_el_gate_no_gasta_presupuesto(self):
        # Rechazar es gratis: un rostro borroso no debe robarle el turno a otro
        # que si se puede reconocer.
        pipeline.apta_para_reconocimiento = _Calidad(rechazar_x=(10,))
        rec = _ReconocedorFalso()
        matched = [(None, _rostro(10)), (None, _rostro(200))]
        decisiones, _ = self.planificar(matched, rec, presupuesto=1)

        self.assertEqual(decisiones[0].motivo_gate, "borroso")
        self.assertEqual(rec.llamadas[0], [(200, 100, 320, 220)])


class TestGates(BaseLote):

    def test_la_pose_mala_no_llega_al_motor(self):
        pipeline.pose_apta_para_reconocimiento = lambda *a, **k: (False, "muy girado")
        rec = _ReconocedorFalso()
        decisiones, _ = self.planificar([(None, _rostro(10))], rec)

        self.assertEqual(rec.llamadas, [])
        self.assertEqual(decisiones[0].motivo_gate, "muy girado")
        self.assertIsNone(decisiones[0].embedding)

    def test_el_cooldown_se_respeta_por_track(self):
        rec = _ReconocedorFalso()
        listo = PersonaTrack((10, 100, 130, 220), 0.0, "frontal")
        listo.t_proximo_embedding = 500.0        # ya le toca
        esperando = PersonaTrack((200, 100, 320, 220), 0.0, "frontal")
        esperando.t_proximo_embedding = 5000.0   # todavia no

        decisiones, _ = self.planificar(
            [(listo, _rostro(10)), (esperando, _rostro(200))], rec, ahora=1000.0
        )
        self.assertEqual(rec.llamadas[0], [(10, 100, 130, 220)])
        self.assertIsNotNone(decisiones[0])
        self.assertIsNone(decisiones[1])


class TestFrameNativo(BaseLote):

    def test_recorta_del_frame_nativo_cuando_hay_reduccion(self):
        # Con la camara a 1280 el embedding sale del frame nativo, y el lote
        # tiene que usar ESA imagen, no la reducida: si no, se recortaria con
        # coordenadas del doble de tamano sobre la imagen pequena.
        nativo = np.zeros((960, 1280, 3), dtype=np.uint8)
        rec = _ReconocedorFalso()
        decisiones, rgb_full = self.planificar(
            [(None, _rostro(10))], rec, escala=2.0, nativo=nativo
        )
        # El bbox llega reproyectado (x2)
        self.assertEqual(rec.llamadas[0][0][0], 20)
        self.assertIsNotNone(rgb_full)
        self.assertEqual(rgb_full.shape[:2], (960, 1280))


if __name__ == "__main__":
    unittest.main()
