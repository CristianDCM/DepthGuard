"""
Tests de como se reparten las cabeceras de Supabase.

Fija el fallo que rompio el nodo edge en produccion: el token de dispositivo
se estaba enviando tambien como `apikey`, y la puerta de entrada del proyecto
solo acepta ahi la clave anon o la service_role. Devolvia 401 "Invalid API
key" antes siquiera de mirar la firma.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.supabase_cliente as sc
from backend.claves import EDGE, SERVICE_ROLE, ClaveAusenteError

ANON = "clave-anon"
EDGE_TOKEN = "token-del-edge"
SERVICE = "clave-service-role"


class TestClaveDeDispositivo(unittest.TestCase):
    """Con la clave restringida, las dos cabeceras deben ser DISTINTAS."""

    def _argumentos(self, anon=ANON):
        with mock.patch.object(sc, "SUPABASE_ANON_KEY", anon), \
             mock.patch.object(sc, "SUPABASE_URL", "https://x.supabase.co"):
            return sc._argumentos_cliente(EDGE_TOKEN, EDGE)

    def test_apikey_es_la_anon_no_el_token(self):
        _, apikey, _ = self._argumentos()
        self.assertEqual(apikey, ANON)
        self.assertNotEqual(
            apikey, EDGE_TOKEN,
            "el token del edge como apikey es justo lo que devuelve 401"
        )

    def test_authorization_lleva_el_token_del_edge(self):
        _, _, opciones = self._argumentos()
        self.assertEqual(
            opciones.headers["Authorization"], f"Bearer {EDGE_TOKEN}"
        )

    def test_sin_anon_falla_con_un_mensaje_que_explica_por_que(self):
        """
        Antes esto acababa en un 401 opaco desde Supabase. Ahora se detecta en
        el arranque y se dice que falta.
        """
        with self.assertRaises(ClaveAusenteError) as ctx:
            self._argumentos(anon="")
        mensaje = str(ctx.exception)
        self.assertIn("SUPABASE_ANON_KEY", mensaje)
        self.assertIn("apikey", mensaje)


class TestServiceRole(unittest.TestCase):
    """El modo heredado no cambia: esa clave si vale como apikey."""

    def test_no_separa_las_cabeceras(self):
        with mock.patch.object(sc, "SUPABASE_URL", "https://x.supabase.co"):
            _, apikey, opciones = sc._argumentos_cliente(SERVICE, SERVICE_ROLE)
        self.assertEqual(apikey, SERVICE)
        self.assertIsNone(opciones)

    def test_no_necesita_la_anon(self):
        with mock.patch.object(sc, "SUPABASE_ANON_KEY", ""), \
             mock.patch.object(sc, "SUPABASE_URL", "https://x.supabase.co"):
            _, apikey, _ = sc._argumentos_cliente(SERVICE, SERVICE_ROLE)
        self.assertEqual(apikey, SERVICE)


class TestUrl(unittest.TestCase):

    def test_la_url_se_propaga_en_ambos_modos(self):
        url = "https://proyecto.supabase.co"
        with mock.patch.object(sc, "SUPABASE_URL", url), \
             mock.patch.object(sc, "SUPABASE_ANON_KEY", ANON):
            self.assertEqual(sc._argumentos_cliente(EDGE_TOKEN, EDGE)[0], url)
            self.assertEqual(sc._argumentos_cliente(SERVICE, SERVICE_ROLE)[0], url)


if __name__ == "__main__":
    unittest.main()
