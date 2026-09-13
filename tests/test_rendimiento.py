"""
Reparto del tiempo de frame, y desacople de la ventana de preview.

Contexto: el stream WebRTC en vivo se ralentizaba al minimizar la ventana local
de OpenCV. El stream en si no puede ralentizarse —el track de aiortc duerme
1/30 s y reusa el ultimo frame, asi que sigue enviando a 30 FPS— lo que se
ralentiza es el CONTENIDO, porque quien produce frames nuevos es el bucle del
pipeline. Y ese bucle llama a cv2.imshow y cv2.waitKey dentro de si mismo, asi
que el coste de la ventana, y cualquier cosa que el sistema operativo haga con
ella, sale del presupuesto de tiempo de cada frame.

De ahi las dos cosas que se prueban aqui: que se puede quitar la ventana del
camino critico, y que el reparto de tiempo se mide para no tener que suponer
donde se va.
"""

import unittest

import numpy as np


class TestCronometro(unittest.TestCase):

    def _crono(self):
        from motor_ia.pipeline import Cronometro
        return Cronometro()

    def test_no_informa_sin_frames(self):
        # Dividir entre cero frames al calcular ms/frame seria un crash en el
        # camino de diagnostico, que es el peor sitio para tener uno.
        c = self._crono()
        self.assertFalse(c.toca_informar(c._t0 + 100))

    def test_informa_pasado_el_intervalo(self):
        c = self._crono()
        c.empezar(); c.marcar("captura"); c.fin_de_frame()
        self.assertFalse(c.toca_informar(c._t0 + 1.0))
        self.assertTrue(c.toca_informar(c._t0 + 3.5))

    def test_el_informe_reparte_por_etapas(self):
        c = self._crono()
        for _ in range(3):
            c.empezar()
            c.marcar("captura")
            c.marcar("deteccion")
            c.fin_de_frame()
        linea = c.informe(c._t0 + 3.0)
        self.assertIn("FPS", linea)
        for etapa in ("captura", "deteccion", "preview", "webrtc", "espera"):
            self.assertIn(etapa, linea)

    def test_el_informe_reinicia_los_contadores(self):
        c = self._crono()
        c.empezar(); c.marcar("captura"); c.fin_de_frame()
        c.informe(c._t0 + 3.0)
        self.assertEqual(c._frames, 0)
        self.assertFalse(c.toca_informar(c._t0 + 3.0))

    def test_una_etapa_desconocida_no_revienta(self):
        # Si alguien anade una marca y se equivoca en el nombre, el diagnostico
        # no debe tirar el pipeline entero.
        c = self._crono()
        c.empezar()
        c.marcar("etapa_que_no_existe")
        c.fin_de_frame()
        self.assertIn("FPS", c.informe(c._t0 + 3.0))

    def test_los_fps_se_calculan_sobre_el_tiempo_real(self):
        c = self._crono()
        for _ in range(30):
            c.empezar(); c.marcar("captura"); c.fin_de_frame()
        linea = c.informe(c._t0 + 3.0)
        self.assertIn("10.0 FPS", linea)


class TestPreviewDesacoplado(unittest.TestCase):
    """
    Con MOSTRAR_PREVIEW=false el pipeline no debe tocar cv2.imshow.

    Es el arreglo de fondo: una ventana de depuracion no deberia poder degradar
    el stream de produccion.
    """

    def _correr(self, mostrar, frames=3):
        import queue
        import motor_ia.pipeline as pipeline
        from motor_ia.deteccion.face_mesh import DetectorFaceMesh, RostroDetectado
        from motor_ia.estado_registro import EstadoRegistro

        originales = {
            "crear_camara": pipeline.crear_camara,
            "cargar": pipeline._cargar_usuarios_supabase,
            "preview_fn": pipeline.mostrar_preview,
            "snapshot": pipeline.subir_snapshot,
            "cliente": pipeline.obtener_cliente,
            "mostrar": pipeline.MOSTRAR_PREVIEW,
            "detectar": DetectorFaceMesh.detectar,
        }

        class _Camara:
            profundidad_real = False
            def conectar(self): pass
            def obtener_frames(self):
                return np.zeros((480, 640, 3), dtype=np.uint8), None
            def cerrar(self): pass

        llamadas = {"imshow": 0, "frames": 0}

        def preview_falso(vista):
            llamadas["imshow"] += 1
            return False

        puntos = np.zeros((468, 2), dtype=np.float32)
        puntos[:] = (320.0, 240.0)
        rostro = RostroDetectado((280, 200, 360, 280), 0.0, 0.0, "frontal", puntos)

        class _Provider:
            def update_frame(self, f):
                llamadas["frames"] += 1
                if llamadas["frames"] >= frames:
                    raise SystemExit

        try:
            pipeline.crear_camara = lambda: _Camara()
            pipeline._cargar_usuarios_supabase = lambda: []
            pipeline.mostrar_preview = preview_falso
            pipeline.subir_snapshot = lambda f: None
            pipeline.obtener_cliente = lambda: None
            pipeline.MOSTRAR_PREVIEW = mostrar
            DetectorFaceMesh.detectar = lambda self, img: [rostro]

            try:
                pipeline.ejecutar_pipeline(
                    queue.Queue(), EstadoRegistro(), frame_provider=_Provider()
                )
            except SystemExit:
                pass
            return llamadas
        finally:
            pipeline.crear_camara = originales["crear_camara"]
            pipeline._cargar_usuarios_supabase = originales["cargar"]
            pipeline.mostrar_preview = originales["preview_fn"]
            pipeline.subir_snapshot = originales["snapshot"]
            pipeline.obtener_cliente = originales["cliente"]
            pipeline.MOSTRAR_PREVIEW = originales["mostrar"]
            DetectorFaceMesh.detectar = originales["detectar"]

    def test_con_preview_apagado_no_se_dibuja_ventana(self):
        llamadas = self._correr(mostrar=False)
        self.assertEqual(llamadas["imshow"], 0)
        # Y el stream SIGUE alimentandose: es el punto de poder apagarla.
        self.assertGreaterEqual(llamadas["frames"], 3)

    def test_con_preview_encendido_si_se_dibuja(self):
        llamadas = self._correr(mostrar=True)
        self.assertGreater(llamadas["imshow"], 0)

    def test_el_defecto_conserva_la_ventana(self):
        # Apagarla por defecto cambiaria el comportamiento a quien depende de
        # ella para trabajar. Es una opcion, no una imposicion.
        from config.settings import MOSTRAR_PREVIEW
        self.assertTrue(MOSTRAR_PREVIEW)


if __name__ == "__main__":
    unittest.main()
