"""Tests para el módulo de reconocimiento facial."""

import sys
import os
import io
import unittest
from unittest import mock
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial


class TestReconocedorFacial(unittest.TestCase):

    def setUp(self):
        self.reconocedor = ReconocedorFacial()
        # Suprimir prints con emojis que fallan en cp1252 (Windows)
        self._original_stdout = sys.stdout
        sys.stdout = io.StringIO()

    def tearDown(self):
        sys.stdout = self._original_stdout

    def test_cache_vacia_retorna_none(self):
        """Buscar sin usuarios cargados debe retornar None."""
        embedding = np.random.randn(128)
        nombre, confianza, uid = self.reconocedor.buscar(embedding)
        self.assertIsNone(nombre)
        self.assertEqual(confianza, 0.0)
        self.assertIsNone(uid)

    def test_confianza_escala_0_1(self):
        """La confianza debe estar en escala 0.0-1.0 (el frontend multiplica por 100)."""
        # Crear un embedding conocido y cargarlo en caché
        emb_referencia = np.random.randn(128)
        emb_referencia = emb_referencia / np.linalg.norm(emb_referencia)

        self.reconocedor.cargar_cache([{
            "id": "test-uuid-123",
            "nombre": "TestUser",
            "embeddings": [emb_referencia.tolist()],
        }])

        # Buscar con el mismo embedding (match perfecto)
        nombre, confianza, uid = self.reconocedor.buscar(emb_referencia)
        self.assertIsNotNone(nombre)
        self.assertGreater(confianza, 0.0)
        self.assertLessEqual(confianza, 1.0,
                             f"confianza={confianza} está fuera de escala 0-1. "
                             f"¿Se está retornando en escala 0-100?")

    def test_match_perfecto_retorna_nombre_y_id(self):
        """Un embedding idéntico al de caché debe hacer match."""
        emb = np.random.randn(128)
        emb = emb / np.linalg.norm(emb)

        self.reconocedor.cargar_cache([{
            "id": "uuid-abc",
            "nombre": "María",
            "embeddings": [emb.tolist()],
        }])

        nombre, confianza, uid = self.reconocedor.buscar(emb)
        self.assertEqual(nombre, "María")
        self.assertEqual(uid, "uuid-abc")

    def test_embedding_lejano_no_hace_match(self):
        """Un embedding muy diferente no debe hacer match."""
        emb_cache = np.ones(128) / np.sqrt(128)
        emb_query = -np.ones(128) / np.sqrt(128)  # Dirección opuesta

        self.reconocedor.cargar_cache([{
            "id": "uuid-xyz",
            "nombre": "Pedro",
            "embeddings": [emb_cache.tolist()],
        }])

        nombre, confianza, uid = self.reconocedor.buscar(emb_query)
        self.assertIsNone(nombre)

    def test_cargar_multiples_usuarios(self):
        """La caché debe manejar múltiples usuarios con múltiples embeddings."""
        self.reconocedor.cargar_cache([
            {
                "id": "u1",
                "nombre": "Ana",
                "embeddings": [np.random.randn(128).tolist(),
                               np.random.randn(128).tolist()],
            },
            {
                "id": "u2",
                "nombre": "Luis",
                "embeddings": [np.random.randn(128).tolist()],
            },
        ])
        # 2 embeddings de Ana + 1 de Luis = 3 entradas en caché
        self.assertEqual(len(self.reconocedor.cache), 3)

    def test_recargar_cache_reemplaza(self):
        """recargar_cache debe reemplazar la caché anterior, no acumular."""
        self.reconocedor.cargar_cache([{
            "id": "u1", "nombre": "A",
            "embeddings": [np.zeros(128).tolist()],
        }])
        self.assertEqual(len(self.reconocedor.cache), 1)

        self.reconocedor.recargar_cache([{
            "id": "u2", "nombre": "B",
            "embeddings": [np.ones(128).tolist()],
        }])
        self.assertEqual(len(self.reconocedor.cache), 1)
        self.assertEqual(self.reconocedor.cache[0]["nombre"], "B")


if __name__ == "__main__":
    unittest.main()
