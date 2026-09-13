"""Tests del seguimiento de personas y la votación temporal."""

import sys
import os
import time
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.tracking import (
    PersonaTrack, asociar_detecciones, escalar_bbox, iou,
    persona_mas_grande, prioridad_reconocimiento,
)
from config.settings import VOTOS_REQUERIDOS, VOTOS_VENTANA


# Sustituto mínimo de RostroDetectado: asociar_detecciones solo usa .bbox
Det = namedtuple("Det", ["bbox"])


def _track(bbox):
    return PersonaTrack(bbox, 0.0, "frontal")


class TestIoU(unittest.TestCase):

    def test_identicos(self):
        self.assertAlmostEqual(iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)

    def test_disjuntos(self):
        self.assertEqual(iou((0, 0, 10, 10), (50, 50, 60, 60)), 0.0)

    def test_solape_parcial(self):
        # Solape de 5x10=50; union = 100 + 100 - 50 = 150
        self.assertAlmostEqual(iou((0, 0, 10, 10), (5, 0, 15, 10)), 50 / 150)

    def test_bbox_degenerado(self):
        self.assertEqual(iou((0, 0, 0, 0), (0, 0, 10, 10)), 0.0)


class TestAsociarDetecciones(unittest.TestCase):

    def test_sin_tracks_todo_es_nuevo(self):
        dets = [Det((0, 0, 50, 50)), Det((100, 100, 150, 150))]
        res = asociar_detecciones([], dets)
        self.assertEqual([t for t, _ in res], [None, None])
        self.assertEqual([d for _, d in res], dets)

    def test_mantiene_el_orden_de_las_detecciones(self):
        t = _track((0, 0, 50, 50))
        dets = [Det((200, 200, 250, 250)), Det((2, 2, 52, 52))]
        res = asociar_detecciones([t], dets)

        self.assertEqual([d for _, d in res], dets)
        self.assertIsNone(res[0][0])       # la lejana es nueva
        self.assertIs(res[1][0], t)       # la solapada es el track

    def test_no_intercambia_identidades_entre_personas_cercanas(self):
        """
        El caso que rompía el greedy anterior: dos personas próximas y las
        detecciones llegando en el orden "equivocado". Con asignación por
        orden de llegada, la primera detección se quedaba el track de la
        otra persona y ambas intercambiaban su sesión reconocida.
        """
        track_a = _track((0, 0, 100, 100))       # persona A, izquierda
        track_b = _track((90, 0, 190, 100))      # persona B, derecha

        # Detecciones en orden inverso, cada una casi encima de su track
        det_b = Det((92, 2, 192, 102))
        det_a = Det((2, 2, 102, 102))

        res = asociar_detecciones([track_a, track_b], [det_b, det_a])
        asignado = {id(det): track for track, det in res}

        self.assertIs(asignado[id(det_a)], track_a)
        self.assertIs(asignado[id(det_b)], track_b)

    def test_un_track_no_se_asigna_dos_veces(self):
        t = _track((0, 0, 100, 100))
        res = asociar_detecciones([t], [Det((0, 0, 100, 100)), Det((5, 5, 105, 105))])
        asignados = [track for track, _ in res if track is not None]
        self.assertEqual(len(asignados), 1)

    def test_respaldo_por_centroide_con_movimiento_rapido(self):
        """Sin solape (IoU=0) pero cerca: sigue siendo el mismo track."""
        t = _track((0, 0, 40, 40))
        res = asociar_detecciones([t], [Det((50, 0, 90, 40))])
        self.assertIs(res[0][0], t)

    def test_salto_grande_crea_track_nuevo(self):
        t = _track((0, 0, 40, 40))
        res = asociar_detecciones([t], [Det((500, 400, 540, 440))])
        self.assertIsNone(res[0][0])


class TestVotacionTemporal(unittest.TestCase):

    def test_un_solo_voto_no_alcanza_veredicto(self):
        """La protección clave: una única inferencia no emite evento."""
        t = _track((0, 0, 50, 50))
        t.registrar_voto("u1", "Ana", 0.9)

        hay, uid, nombre, conf = t.veredicto()
        self.assertFalse(hay)
        self.assertIsNone(uid)
        self.assertIsNone(nombre)

    def test_mayoria_produce_veredicto(self):
        t = _track((0, 0, 50, 50))
        for _ in range(VOTOS_REQUERIDOS):
            t.registrar_voto("u1", "Ana", 0.8)

        hay, uid, nombre, conf = t.veredicto()
        self.assertTrue(hay)
        self.assertEqual(uid, "u1")
        self.assertEqual(nombre, "Ana")

    def test_un_voto_erroneo_no_gana_a_la_mayoria(self):
        """Escenario real: 1 de N inferencias identifica a otra persona."""
        t = _track((0, 0, 50, 50))
        t.registrar_voto("u2", "Intruso", 0.95)   # error puntual, muy confiado
        for _ in range(VOTOS_REQUERIDOS):
            t.registrar_voto("u1", "Ana", 0.7)

        hay, uid, nombre, _ = t.veredicto()
        self.assertTrue(hay)
        self.assertEqual(uid, "u1")
        self.assertEqual(nombre, "Ana")

    def test_empate_no_produce_veredicto(self):
        """Con votos repartidos y sin mayoría suficiente, no se decide."""
        t = _track((0, 0, 50, 50))
        t.registrar_voto("u1", "Ana", 0.8)
        t.registrar_voto("u2", "Luis", 0.8)

        self.assertFalse(t.veredicto()[0])

    def test_desconocido_tambien_vota(self):
        """DESCONOCIDO necesita mayoría igual que una identificación."""
        t = _track((0, 0, 50, 50))
        t.registrar_voto(None, None, 0.0)
        self.assertFalse(t.veredicto()[0])

        for _ in range(VOTOS_REQUERIDOS - 1):
            t.registrar_voto(None, None, 0.0)

        hay, uid, nombre, _ = t.veredicto()
        self.assertTrue(hay)
        self.assertIsNone(uid)
        self.assertIsNone(nombre)

    def test_confianza_es_la_mejor_del_ganador(self):
        t = _track((0, 0, 50, 50))
        t.registrar_voto("u1", "Ana", 0.61)
        t.registrar_voto("u1", "Ana", 0.88)
        for _ in range(VOTOS_REQUERIDOS - 2):
            t.registrar_voto("u1", "Ana", 0.55)

        self.assertAlmostEqual(t.veredicto()[3], 0.88)

    def test_ventana_es_deslizante(self):
        """Los votos viejos salen de la ventana y dejan de contar."""
        t = _track((0, 0, 50, 50))
        for _ in range(VOTOS_VENTANA):
            t.registrar_voto("u1", "Ana", 0.8)
        self.assertEqual(t.veredicto()[1], "u1")

        # Rellenar la ventana entera con otra identidad
        for _ in range(VOTOS_VENTANA):
            t.registrar_voto("u2", "Luis", 0.8)
        self.assertEqual(t.veredicto()[1], "u2")

    def test_limpiar_votos_resetea(self):
        t = _track((0, 0, 50, 50))
        for _ in range(VOTOS_REQUERIDOS):
            t.registrar_voto("u1", "Ana", 0.8)
        t.limpiar_votos()
        self.assertFalse(t.veredicto()[0])


class TestEscalarBbox(unittest.TestCase):

    def test_escala_al_frame_nativo(self):
        # bbox detectado en 640px sobre una cámara de 1920px -> escala 3
        self.assertEqual(
            escalar_bbox((10, 20, 110, 140), 3.0, 1920, 1080),
            (30, 60, 330, 420)
        )

    def test_recorta_al_tamano_del_frame(self):
        x, y, x2, y2 = escalar_bbox((600, 400, 640, 480), 3.0, 1920, 1080)
        self.assertLessEqual(x2, 1920)
        self.assertLessEqual(y2, 1080)

    def test_escala_unitaria_no_cambia_nada(self):
        bbox = (10, 20, 110, 140)
        self.assertEqual(escalar_bbox(bbox, 1.0, 640, 480), bbox)


class TestPrioridadReconocimiento(unittest.TestCase):
    """
    El presupuesto de embeddings por frame es limitado (un embedding cuesta
    del orden de 100 ms y el bucle es de un solo hilo), así que el orden en
    que se reparte importa.
    """

    def _par(self, sesion_tipo, lado):
        track = _track((0, 0, lado, lado))
        track.sesion_tipo = sesion_tipo
        return (track, Det((0, 0, lado, lado)))

    def test_sin_veredicto_va_antes_que_resuelto(self):
        resuelto = self._par("ACCESO_PERMITIDO", 200)
        pendiente = self._par(None, 50)

        orden = sorted([resuelto, pendiente], key=prioridad_reconocimiento)
        self.assertIs(orden[0], pendiente)

    def test_entre_pendientes_gana_el_mas_cercano(self):
        lejos = self._par(None, 60)
        cerca = self._par(None, 200)

        orden = sorted([lejos, cerca], key=prioridad_reconocimiento)
        self.assertIs(orden[0], cerca)

    def test_track_nuevo_cuenta_como_pendiente(self):
        """Una persona que acaba de aparecer (track=None) es prioritaria."""
        resuelto = self._par("ACCESO_PERMITIDO", 300)
        nuevo = (None, Det((0, 0, 40, 40)))

        orden = sorted([resuelto, nuevo], key=prioridad_reconocimiento)
        self.assertIs(orden[0], nuevo)

    def test_desconocido_ya_resuelto_no_es_prioritario(self):
        """DESCONOCIDO también es un veredicto: no hay que re-decidirlo ya."""
        desconocido = self._par("DESCONOCIDO", 300)
        pendiente = self._par(None, 40)

        orden = sorted([desconocido, pendiente], key=prioridad_reconocimiento)
        self.assertIs(orden[0], pendiente)

    def test_fraude_sigue_siendo_pendiente_de_identificar(self):
        """FRAUDE no es un veredicto de identidad."""
        fraude = self._par("FRAUDE", 100)
        resuelto = self._par("ACCESO_PERMITIDO", 300)

        orden = sorted([resuelto, fraude], key=prioridad_reconocimiento)
        self.assertIs(orden[0], fraude)


class TestVarios(unittest.TestCase):

    def test_persona_mas_grande(self):
        chico = _track((0, 0, 20, 20))
        grande = _track((0, 0, 100, 100))
        self.assertIs(persona_mas_grande([chico, grande]), grande)
        self.assertIsNone(persona_mas_grande([]))

    def test_track_expira(self):
        t = _track((0, 0, 50, 50))
        self.assertTrue(t.esta_activo(time.time()))
        self.assertFalse(t.esta_activo(time.time() + 3600))

    def test_to_vis_dict_incluye_motivo_gate(self):
        t = _track((0, 0, 50, 50))
        t.motivo_gate = "Rostro muy girado (yaw: 50)"
        self.assertEqual(t.to_vis_dict()["motivo_gate"], "Rostro muy girado (yaw: 50)")


if __name__ == "__main__":
    unittest.main()
