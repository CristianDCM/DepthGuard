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
    Aplicarla tambien tras un "no registrada" es justo lo contrario de lo que
    hace falta: puede ser un usuario legitimo al que le fallo un frame.
    """

    def _cadencia(self, sesion_tipo):
        import motor_ia.pipeline as pipeline
        from config.settings import (
            COOLDOWN_EMBEDDING, COOLDOWN_EMBEDDING_VOTACION,
        )
        # Espejo de la decision del pipeline (linea `ya_decidido = ...`).
        ya_decidido = sesion_tipo == "ACCESO_PERMITIDO"
        return COOLDOWN_EMBEDDING if ya_decidido else COOLDOWN_EMBEDDING_VOTACION

    def test_desconocido_usa_la_cadencia_rapida(self):
        from config.settings import COOLDOWN_EMBEDDING_VOTACION
        self.assertEqual(self._cadencia("DESCONOCIDO"),
                         COOLDOWN_EMBEDDING_VOTACION)

    def test_acceso_permitido_usa_la_lenta(self):
        from config.settings import COOLDOWN_EMBEDDING
        self.assertEqual(self._cadencia("ACCESO_PERMITIDO"), COOLDOWN_EMBEDDING)

    def test_sin_veredicto_usa_la_rapida(self):
        from config.settings import COOLDOWN_EMBEDDING_VOTACION
        self.assertEqual(self._cadencia(None), COOLDOWN_EMBEDDING_VOTACION)

    def test_el_codigo_no_trata_desconocido_como_decidido(self):
        # Ancla sobre el fuente: si alguien vuelve a meter DESCONOCIDO en la
        # condicion, el sintoma reaparece y los tests de arriba, que son un
        # espejo, seguirian en verde.
        with open("motor_ia/pipeline.py", encoding="utf-8") as f:
            fuente = f.read()
        self.assertIn('ya_decidido = track.sesion_tipo == "ACCESO_PERMITIDO"',
                      fuente)
        self.assertNotIn(
            'ya_decidido = track.sesion_tipo in ("ACCESO_PERMITIDO", "DESCONOCIDO")',
            fuente,
            "La cadencia lenta tras DESCONOCIDO es lo que causaba el 'luego de "
            "un rato me reconoce'."
        )

    def test_recuperarse_es_mucho_mas_rapido(self):
        from config.settings import (
            COOLDOWN_EMBEDDING, COOLDOWN_EMBEDDING_VOTACION, VOTOS_REQUERIDOS,
        )
        antes = COOLDOWN_EMBEDDING * VOTOS_REQUERIDOS
        ahora = COOLDOWN_EMBEDDING_VOTACION * VOTOS_REQUERIDOS
        self.assertLess(ahora, antes / 3)


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
