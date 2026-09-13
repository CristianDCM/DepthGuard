"""
Tests de que clave usa la senalizacion WebRTC (hallazgo C2).

Con canal publico conviene la clave sin privilegios. Con canal privado hace
falta una identidad que pase la RLS de realtime.messages, y la anon no la pasa.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.claves import clave_realtime

BASE = dict(edge_key="EDGE", service_key="SERVICE", permitir_service=True)


class TestCanalPublico(unittest.TestCase):

    def test_usa_la_anon(self):
        """Broadcast puro: no toca ninguna tabla, no necesita privilegios."""
        self.assertEqual(
            clave_realtime("ANON", canal_privado=False, **BASE), "ANON"
        )

    def test_sin_anon_cae_a_la_de_datos(self):
        self.assertEqual(
            clave_realtime("", canal_privado=False, **BASE), "EDGE"
        )


class TestCanalPrivado(unittest.TestCase):

    def test_usa_la_clave_del_edge_aunque_haya_anon(self):
        """
        La anon no pasa una politica escrita para identidades autenticadas,
        asi que con canal privado hace falta la clave del edge.
        """
        self.assertEqual(
            clave_realtime("ANON", canal_privado=True, **BASE), "EDGE"
        )

    def test_nunca_devuelve_la_anon_con_canal_privado(self):
        for anon in ("ANON", "", None):
            with self.subTest(anon=anon):
                self.assertNotEqual(
                    clave_realtime(anon, canal_privado=True, **BASE), "ANON"
                )

    def test_sin_clave_de_edge_cae_a_service_role(self):
        """
        Instalacion sin migrar: service_role salta la RLS, asi que entra al
        canal igualmente. Lo avisa el informe de postura (hallazgo C3).
        """
        self.assertEqual(
            clave_realtime("ANON", canal_privado=True,
                           edge_key="", service_key="SERVICE",
                           permitir_service=True),
            "SERVICE",
        )


if __name__ == "__main__":
    unittest.main()
