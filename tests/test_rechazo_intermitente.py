"""
El fallo de "persona no registrada en ratos, y luego me reconoce".

Diagnostico, con numeros medidos sobre un enrolamiento real:

  * Las 5 plantillas de un mismo usuario distan entre si hasta 0.857 (es
    variacion de pose legitima; se verifico que ninguna es atipica).
  * El jitter de los landmarks del detector mueve el embedding 0.14 de mediana
    y 0.37 en el peor caso.
  * La luz y el enfoque anaden entre 0.23 y 0.49.

Con el umbral viejo (1.095) una pose intermedia con un frame algo desenfocado
aterrizaba en 1.09: el 100% del umbral. El sistema vivia en el borde, que es el
peor sitio posible —funciona casi siempre— y cada fallo declaraba "no
registrada" a un usuario legitimo.

Y despues de declararlo, la cadencia de re-comprobacion bajaba a la lenta
(2 s), asi que recuperarse exigia 3 aciertos a 2 s = 6 segundos como minimo.
De ahi el "luego de un rato".
"""

import unittest
from unittest import mock

import numpy as np


class TestCadenciaTrasDesconocido(unittest.TestCase):
    """
    Tras declarar DESCONOCIDO hay que volver a mirar RAPIDO.

    La cadencia lenta esta pensada para re-confirmar a quien ya se identifico.
    Aplicarla tambien tras un "no registrada" es lo contrario de lo que hace
    falta: puede ser un usuario legitimo al que le fallo un frame, y esperar 2 s
    por intento convierte 3 votos en 6 segundos de "no te reconozco".

    Este test EJECUTA el pipeline y mide el cooldown que asigna de verdad.
    La version anterior duplicaba la decision del pipeline en el propio test y
    comprobaba su copia, asi que habria seguido en verde aunque la linea real
    estuviera mal. Un test circular es peor que ninguno: da confianza sin
    comprobar nada.
    """

    def _cooldown_medido(self, sesion_tipo):
        """
        Corre el pipeline y devuelve el cooldown que asigna a un track cuyo
        sesion_tipo es `sesion_tipo`.

        Se aprovecha que mostrar_preview se llama una vez por frame, DESPUES de
        que el bucle haya asignado el cooldown: sirve de gancho para forzar el
        estado entre frames y para leer el resultado.
        """
        import queue
        import time
        import motor_ia.pipeline as pipeline
        from motor_ia.deteccion.face_mesh import DetectorFaceMesh, RostroDetectado
        from motor_ia.estado_registro import EstadoRegistro
        from motor_ia.tracking import PersonaTrack

        originales = {
            "crear_camara": pipeline.crear_camara,
            "cargar": pipeline._cargar_usuarios_supabase,
            "preview": pipeline.mostrar_preview,
            "snapshot": pipeline.subir_snapshot,
            "cliente": pipeline.obtener_cliente,
            "calidad": pipeline.apta_para_reconocimiento,
            "pose": pipeline.pose_apta_para_reconocimiento,
            "detectar": DetectorFaceMesh.detectar,
            "init": PersonaTrack.__init__,
        }

        class _Camara:
            profundidad_real = False
            def conectar(self): pass
            def obtener_frames(self):
                return np.zeros((480, 640, 3), dtype=np.uint8), None
            def cerrar(self): pass

        puntos = np.zeros((468, 2), dtype=np.float32)
        puntos[:] = (320.0, 240.0)
        rostro = RostroDetectado((280, 200, 360, 280), 0.0, 0.0, "frontal", puntos)

        tracks = []
        def init_espia(self, *a, **k):
            originales["init"](self, *a, **k)
            tracks.append(self)

        medido = {"cooldown": None}
        frames = {"n": 0}

        def preview(vista):
            frames["n"] += 1
            if not tracks:
                return frames["n"] >= 6

            track = tracks[0]
            if frames["n"] == 1:
                # Forzar el estado y volver a habilitar el turno, para que el
                # siguiente frame pase por la linea que se quiere medir.
                track.sesion_tipo = sesion_tipo
                track.t_proximo_embedding = 0
            elif medido["cooldown"] is None and track.t_proximo_embedding > 0:
                medido["cooldown"] = track.t_proximo_embedding - time.time()
                return True
            return frames["n"] >= 6

        try:
            pipeline.crear_camara = lambda: _Camara()
            pipeline._cargar_usuarios_supabase = lambda: []
            pipeline.mostrar_preview = preview
            pipeline.subir_snapshot = lambda f: None
            pipeline.obtener_cliente = lambda: None
            pipeline.apta_para_reconocimiento = lambda *a, **k: (True, "OK")
            pipeline.pose_apta_para_reconocimiento = lambda *a, **k: (True, "")
            DetectorFaceMesh.detectar = lambda self, img: [rostro]
            PersonaTrack.__init__ = init_espia

            pipeline.ejecutar_pipeline(queue.Queue(), EstadoRegistro())
        finally:
            pipeline.crear_camara = originales["crear_camara"]
            pipeline._cargar_usuarios_supabase = originales["cargar"]
            pipeline.mostrar_preview = originales["preview"]
            pipeline.subir_snapshot = originales["snapshot"]
            pipeline.obtener_cliente = originales["cliente"]
            pipeline.apta_para_reconocimiento = originales["calidad"]
            pipeline.pose_apta_para_reconocimiento = originales["pose"]
            DetectorFaceMesh.detectar = originales["detectar"]
            PersonaTrack.__init__ = originales["init"]

        return medido["cooldown"]

    def test_el_pipeline_asigna_la_cadencia_rapida_tras_desconocido(self):
        from config.settings import (
            COOLDOWN_EMBEDDING, COOLDOWN_EMBEDDING_VOTACION,
        )
        cooldown = self._cooldown_medido("DESCONOCIDO")
        self.assertIsNotNone(cooldown, "el pipeline no asigno ningun cooldown")
        # El margen absorbe el tiempo de procesar el frame (unos ms) y es de
        # sobra para distinguir 0.2 s de 2.0 s, que es lo que importa.
        self.assertAlmostEqual(cooldown, COOLDOWN_EMBEDDING_VOTACION, delta=0.15)
        self.assertLess(
            cooldown, COOLDOWN_EMBEDDING / 2,
            f"Tras DESCONOCIDO se esta esperando {cooldown:.2f} s. Con la "
            f"cadencia lenta, recuperarse cuesta segundos y el usuario ve "
            f"'persona no registrada' mientras tanto."
        )

    def test_el_pipeline_asigna_la_cadencia_lenta_tras_conceder_acceso(self):
        # El otro lado: a quien ya se identifico solo hay que re-confirmarlo de
        # vez en cuando. Si esto tambien fuera rapido, se gastaria CPU en
        # comprobar lo que ya se sabe.
        from config.settings import COOLDOWN_EMBEDDING
        cooldown = self._cooldown_medido("ACCESO_PERMITIDO")
        self.assertIsNotNone(cooldown)
        self.assertAlmostEqual(cooldown, COOLDOWN_EMBEDDING, delta=0.15)


class TestDetalleDelRechazo(unittest.TestCase):
    """Un rechazo sin numero no se puede diagnosticar."""

    def _reconocedor(self, n_identidades=1):
        from motor_ia.reconocimiento.embedding_generator import (
            ReconocedorFacial, _DIMENSIONES,
        )
        rec = ReconocedorFacial()
        usuarios = []
        for i in range(n_identidades):
            v = np.zeros(_DIMENSIONES)
            v[i] = 1.0
            usuarios.append({"id": f"u{i}", "nombre": f"P{i}",
                             "embeddings": [v.tolist()]})
        rec.cargar_cache(usuarios)
        return rec, _DIMENSIONES

    def test_un_acierto_no_lleva_motivo(self):
        rec, dim = self._reconocedor()
        v = np.zeros(dim); v[0] = 1.0
        r = rec.evaluar(v)
        self.assertEqual(r.nombre, "P0")
        self.assertEqual(r.motivo, "")
        self.assertAlmostEqual(r.distancia, 0.0, places=6)

    def test_un_rechazo_por_lejania_dice_la_distancia(self):
        rec, dim = self._reconocedor()
        lejos = np.zeros(dim); lejos[-1] = 1.0   # ortogonal: distancia sqrt(2)
        r = rec.evaluar(lejos)
        self.assertIsNone(r.nombre)
        self.assertIn("lejos", r.motivo)
        self.assertIsNotNone(r.distancia)
        # El motivo lleva el numero, que es el punto de todo esto
        self.assertIn(f"{r.distancia:.3f}", r.motivo)

    def test_un_empate_se_distingue_de_una_lejania(self):
        # Dos motivos distintos para dos problemas distintos: uno se arregla
        # con el umbral y el otro registrando mejor a las dos personas.
        from motor_ia.reconocimiento.embedding_generator import _MARGEN
        rec, dim = self._reconocedor(n_identidades=2)
        # Punto equidistante de las dos identidades
        medio = np.zeros(dim); medio[0] = medio[1] = 0.5
        r = rec.evaluar(medio)
        if r.nombre is None and "empate" in r.motivo:
            self.assertIn("segunda", r.motivo)
            self.assertIsNotNone(r.margen)
        else:
            self.skipTest(f"con _MARGEN={_MARGEN} este punto no da empate")

    def test_cache_vacia_lo_dice(self):
        from motor_ia.reconocimiento.embedding_generator import (
            ReconocedorFacial, _DIMENSIONES,
        )
        rec = ReconocedorFacial()
        r = rec.evaluar(np.zeros(_DIMENSIONES))
        self.assertEqual(r.motivo, "sin plantillas")
        self.assertIsNone(r.distancia)

    def test_buscar_sigue_devolviendo_tres_valores(self):
        # Retrocompatibilidad: evaluar() es nuevo, buscar() no debe cambiar.
        rec, dim = self._reconocedor()
        v = np.zeros(dim); v[0] = 1.0
        self.assertEqual(len(rec.buscar(v)), 3)


class TestUmbralConDatosReales(unittest.TestCase):
    """
    El umbral debe cubrir la dispersion real de un mismo usuario.

    Los numeros vienen del enrolamiento en produccion, no de una estimacion.
    """

    # Medido sobre el enrolamiento real: hueco entre las 5 plantillas del
    # mismo usuario.
    HUECO_MAX = 0.857
    # Un frame en vivo cae DENTRO de ese hueco, no en su extremo, asi que su
    # distancia a la plantilla mas cercana es como mucho la mitad. Sumar el
    # hueco completo contaria la misma variacion de pose dos veces.
    PEOR_POSE = HUECO_MAX / 2
    # Medido: ruido que anade cada frame.
    JITTER_PEOR = 0.373
    CONDICIONES_PEOR = 0.488

    def test_el_umbral_cubre_una_pose_intermedia_con_mal_enfoque(self):
        from config.settings import TOLERANCIA_FACIAL_ONNX
        caso = self.PEOR_POSE + self.CONDICIONES_PEOR
        self.assertGreater(
            TOLERANCIA_FACIAL_ONNX, caso,
            f"Con umbral {TOLERANCIA_FACIAL_ONNX} y un caso realista de "
            f"{caso:.3f}, un usuario legitimo sera rechazado 'en ratos'."
        )

    def test_el_umbral_cubre_una_pose_intermedia_con_jitter_malo(self):
        from config.settings import TOLERANCIA_FACIAL_ONNX
        caso = self.PEOR_POSE + self.JITTER_PEOR
        self.assertGreater(TOLERANCIA_FACIAL_ONNX, caso)

    def test_el_todo_a_la_vez_lo_absorbe_la_votacion_no_el_umbral(self):
        # Pose intermedia MAS jitter malo MAS mal enfoque, todo en el mismo
        # frame, se va por encima de cualquier umbral razonable. Subir el umbral
        # hasta cubrirlo aumentaria el riesgo de confundir personas sin haberlo
        # podido validar. Eso lo absorbe la votacion temporal: hacen falta
        # VOTOS_REQUERIDOS fallos de 5 para declarar "no registrada", asi que un
        # frame catastrofico aislado no decide nada.
        from config.settings import TOLERANCIA_FACIAL_ONNX, VOTOS_REQUERIDOS
        todo = self.PEOR_POSE + self.JITTER_PEOR + self.CONDICIONES_PEOR
        self.assertGreater(todo, TOLERANCIA_FACIAL_ONNX)
        self.assertGreater(VOTOS_REQUERIDOS, 1,
                           "Sin votacion, un solo frame malo decidiria.")

    def test_el_umbral_no_es_absurdamente_laxo(self):
        # El otro lado no se puede medir con un solo usuario, pero si se puede
        # evitar un valor sin sentido: a distancia 2.0 dos vectores normalizados
        # son opuestos, asi que cualquier umbral cerca de ahi acepta a
        # cualquiera.
        from config.settings import TOLERANCIA_FACIAL_ONNX
        self.assertLess(TOLERANCIA_FACIAL_ONNX, 1.45)


if __name__ == "__main__":
    unittest.main()
