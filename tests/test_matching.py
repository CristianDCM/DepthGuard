"""
Tests del matching facial: agregación por identidad, test de margen,
confianza calibrada y pista de pose.

Se centran en la lógica de decisión, que es independiente del modelo de
embeddings: los vectores se construyen a mano para colocar las distancias
exactamente donde el test las necesita.
"""

import sys
import os
import io
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.reconocimiento.embedding_generator import (
    ReconocedorFacial, calibrar_confianza,
)
from config.settings import (
    TOLERANCIA_FACIAL, MARGEN_IDENTIDAD, PENALIZACION_POSE,
)


def _vector_a_distancia(base, distancia):
    """Devuelve un vector que está exactamente a `distancia` de `base`."""
    direccion = np.zeros_like(base)
    direccion[0] = 1.0
    return base + direccion * distancia


class TestCalibrarConfianza(unittest.TestCase):

    def test_es_050_en_el_umbral(self):
        """El punto de corte debe leerse como 50%, no como un número arbitrario."""
        self.assertAlmostEqual(calibrar_confianza(TOLERANCIA_FACIAL), 0.5, places=3)

    def test_es_monotona_decreciente(self):
        valores = [calibrar_confianza(d) for d in np.linspace(0.0, 1.2, 25)]
        for anterior, siguiente in zip(valores, valores[1:]):
            self.assertGreater(anterior, siguiente)

    def test_siempre_en_rango_0_1(self):
        for d in [0.0, 0.1, 0.5, 1.0, 5.0, 1e6]:
            conf = calibrar_confianza(d)
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)

    def test_match_bueno_no_parece_dudoso(self):
        """
        Con `1 - distancia`, un match correcto a 0.42 se mostraba como 58%.
        La versión calibrada debe dejarlo claramente por encima.
        """
        self.assertGreater(calibrar_confianza(0.42), 0.7)


class TestTestDeMargen(unittest.TestCase):
    """
    El margen es lo que convierte un empate en un rechazo. Sin él, basta con
    que alguien caiga bajo el umbral para que se le abra la puerta.
    """

    def setUp(self):
        self.reconocedor = ReconocedorFacial()
        self._stdout = sys.stdout
        sys.stdout = io.StringIO()
        self.consulta = np.zeros(128)

    def tearDown(self):
        sys.stdout = self._stdout

    def _cargar(self, distancias):
        """Carga un usuario por cada distancia indicada respecto a la consulta."""
        usuarios = []
        for i, dist in enumerate(distancias):
            usuarios.append({
                "id": f"u{i}",
                "nombre": f"Usuario{i}",
                "embeddings": [_vector_a_distancia(self.consulta, dist).tolist()],
            })
        self.reconocedor.cargar_cache(usuarios)

    def test_acepta_cuando_hay_margen_claro(self):
        self._cargar([0.20, 0.20 + MARGEN_IDENTIDAD * 3])
        nombre, conf, uid = self.reconocedor.buscar(self.consulta)
        self.assertEqual(uid, "u0")
        self.assertGreater(conf, 0.5)

    def test_rechaza_empate_entre_dos_identidades(self):
        """Dos personas casi igual de cerca: es un empate, no una identificación."""
        self._cargar([0.20, 0.20 + MARGEN_IDENTIDAD * 0.5])
        nombre, conf, uid = self.reconocedor.buscar(self.consulta)
        self.assertIsNone(nombre)
        self.assertIsNone(uid)
        self.assertEqual(conf, 0.0)

    def test_un_solo_usuario_no_necesita_margen(self):
        """Con una sola identidad enrolada no hay con quién empatar."""
        self._cargar([0.20])
        nombre, _, uid = self.reconocedor.buscar(self.consulta)
        self.assertEqual(uid, "u0")

    def test_margen_no_salva_una_distancia_fuera_de_umbral(self):
        """El umbral absoluto sigue mandando: lejos es lejos."""
        self._cargar([TOLERANCIA_FACIAL + 0.1, 2.0])
        self.assertIsNone(self.reconocedor.buscar(self.consulta)[0])

    def test_margen_se_mide_entre_identidades_no_entre_plantillas(self):
        """
        Dos plantillas del MISMO usuario a distancias parecidas no son un
        empate: agregar por plantilla habría rechazado este caso.
        """
        self.reconocedor.cargar_cache([
            {
                "id": "u0", "nombre": "Ana",
                "embeddings": [
                    _vector_a_distancia(self.consulta, 0.20).tolist(),
                    _vector_a_distancia(self.consulta, 0.21).tolist(),
                ],
            },
            {
                "id": "u1", "nombre": "Luis",
                "embeddings": [_vector_a_distancia(self.consulta, 0.9).tolist()],
            },
        ])
        nombre, _, uid = self.reconocedor.buscar(self.consulta)
        self.assertEqual(uid, "u0")
        self.assertEqual(nombre, "Ana")


class TestPistaDePose(unittest.TestCase):

    def setUp(self):
        self.reconocedor = ReconocedorFacial()
        self._stdout = sys.stdout
        sys.stdout = io.StringIO()
        self.consulta = np.zeros(128)

    def tearDown(self):
        sys.stdout = self._stdout

    def test_angulos_se_derivan_del_orden_de_captura(self):
        """
        El registro recorre ANGULOS_REGISTRO en secuencia, así que la
        plantilla i corresponde al ángulo i.
        """
        self.reconocedor.cargar_cache([{
            "id": "u0", "nombre": "Ana",
            "embeddings": [np.zeros(128).tolist() for _ in range(5)],
        }])
        angulos = [item["angulo"] for item in self.reconocedor.cache]
        self.assertEqual(
            angulos, ["frontal", "izquierda", "derecha", "arriba", "abajo"]
        )

    def test_etiquetas_explicitas_tienen_prioridad(self):
        self.reconocedor.cargar_cache([{
            "id": "u0", "nombre": "Ana",
            "embeddings": [np.zeros(128).tolist(), np.zeros(128).tolist()],
            "angulos": ["abajo", "arriba"],
        }])
        angulos = [item["angulo"] for item in self.reconocedor.cache]
        self.assertEqual(angulos, ["abajo", "arriba"])

    def test_la_pose_desempata_un_caso_al_borde_del_margen(self):
        """
        La pista de pose actúa sobre casos al borde del margen: el rival que
        solo empata a través de una plantilla de OTRO ángulo se aparta lo
        justo para que el candidato correcto supere el margen.

        La penalización es pequeña a propósito (ver test siguiente), así que
        su efecto es desempatar, no revertir diferencias grandes.
        """
        # u0: plantilla frontal (índice 0) a 0.20
        # u1: frontal muy lejos + "izquierda" (índice 1) a 0.25
        self.reconocedor.cargar_cache([
            {
                "id": "u0", "nombre": "Frontal",
                "embeddings": [_vector_a_distancia(self.consulta, 0.20).tolist()],
            },
            {
                "id": "u1", "nombre": "Girado",
                "embeddings": [
                    _vector_a_distancia(self.consulta, 5.0).tolist(),   # frontal, lejos
                    _vector_a_distancia(self.consulta, 0.25).tolist(),  # izquierda
                ],
            },
        ])

        # Sin pose: 0.25 - 0.20 = 0.05 < MARGEN_IDENTIDAD (0.06) -> rechazo
        self.assertIsNone(self.reconocedor.buscar(self.consulta)[0])

        # Con pose frontal: la plantilla "izquierda" de u1 se penaliza y el
        # margen pasa a 0.07 -> se acepta u0
        nombre, _, uid = self.reconocedor.buscar(self.consulta, pose="frontal")
        self.assertEqual(uid, "u0")
        self.assertEqual(nombre, "Frontal")

    def test_penalizacion_de_pose_es_acotada(self):
        """
        Es una pista suave: si la pose se estima mal, el coste máximo es
        PENALIZACION_POSE, no un rechazo automático.
        """
        self.reconocedor.cargar_cache([{
            "id": "u0", "nombre": "Ana",
            "embeddings": [_vector_a_distancia(self.consulta, 0.20).tolist()],
        }])
        # Plantilla frontal pero pose mal estimada como "abajo"
        nombre, conf, uid = self.reconocedor.buscar(self.consulta, pose="abajo")
        self.assertEqual(uid, "u0")
        self.assertAlmostEqual(conf, calibrar_confianza(0.20 + PENALIZACION_POSE), places=3)


class TestCacheVectorizada(unittest.TestCase):

    def setUp(self):
        self.reconocedor = ReconocedorFacial()
        self._stdout = sys.stdout
        sys.stdout = io.StringIO()

    def tearDown(self):
        sys.stdout = self._stdout

    def test_matriz_y_lista_coinciden(self):
        self.reconocedor.cargar_cache([
            {"id": "u0", "nombre": "A", "embeddings": [np.zeros(128).tolist()] * 3},
            {"id": "u1", "nombre": "B", "embeddings": [np.ones(128).tolist()]},
        ])
        self.assertEqual(self.reconocedor._matriz.shape, (4, 128))
        self.assertEqual(len(self.reconocedor.cache), 4)
        self.assertEqual(len(self.reconocedor._identidades), 2)
        self.assertEqual(list(self.reconocedor._idx_identidad), [0, 0, 0, 1])

    def test_usuario_sin_embeddings_se_ignora(self):
        self.reconocedor.cargar_cache([
            {"id": "u0", "nombre": "A", "embeddings": []},
            {"id": "u1", "nombre": "B"},
            {"id": "u2", "nombre": "C", "embeddings": [np.zeros(128).tolist()]},
        ])
        self.assertEqual(len(self.reconocedor._identidades), 1)
        self.assertEqual(self.reconocedor._identidades[0][0], "u2")

    def test_formato_embedding_singular(self):
        """Compatibilidad con el formato antiguo de un solo embedding."""
        self.reconocedor.cargar_cache([
            {"id": "u0", "nombre": "A", "embedding": np.zeros(128).tolist()},
        ])
        self.assertEqual(self.reconocedor._matriz.shape, (1, 128))

    def test_cache_vacia_no_explota(self):
        self.reconocedor.cargar_cache([])
        self.assertEqual(
            self.reconocedor.buscar(np.zeros(128)), (None, 0.0, None)
        )


if __name__ == "__main__":
    unittest.main()
