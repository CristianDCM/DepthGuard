"""
Tests de la politica de seleccion de clave de Supabase.

Lo que se protege aqui: que el edge nunca opere con mas privilegio del
necesario por accidente de configuracion.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.claves import (
    elegir_clave, clave_realtime, texto_aviso,
    EDGE, SERVICE_ROLE, ClaveInseguraError, ClaveAusenteError,
)


class TestEleccionDeClave(unittest.TestCase):

    def test_clave_restringida_cuando_es_la_unica(self):
        self.assertEqual(elegir_clave("EK", "", True), ("EK", EDGE))

    def test_la_restringida_gana_aunque_haya_service_role(self):
        """
        Tener las dos en el .env no debe degradar al modo mas privilegiado.
        Es el caso tipico a mitad de migracion.
        """
        self.assertEqual(elegir_clave("EK", "SK", True), ("EK", EDGE))

    def test_la_restringida_gana_incluso_con_service_permitida(self):
        clave, modo = elegir_clave("EK", "SK", permitir_service=True)
        self.assertEqual(modo, EDGE)
        self.assertNotEqual(clave, "SK")

    def test_service_role_como_ultimo_recurso(self):
        """Compatibilidad: una instalacion sin migrar sigue arrancando."""
        self.assertEqual(elegir_clave("", "SK", True), ("SK", SERVICE_ROLE))

    def test_service_role_prohibida_falla_cerrado(self):
        """
        Con PERMITIR_SERVICE_KEY=false el sistema debe negarse a arrancar, no
        arrancar de todas formas con una llave maestra en el dispositivo.
        """
        with self.assertRaises(ClaveInseguraError):
            elegir_clave("", "SK", False)

    def test_restringida_funciona_aunque_se_prohiba_service_role(self):
        """La prohibicion no debe estorbar a la configuracion correcta."""
        self.assertEqual(elegir_clave("EK", "SK", False), ("EK", EDGE))

    def test_sin_ninguna_clave_falla(self):
        with self.assertRaises(ClaveAusenteError):
            elegir_clave("", "", True)

    def test_el_error_dice_como_arreglarlo(self):
        with self.assertRaises(ClaveInseguraError) as ctx:
            elegir_clave("", "SK", False)
        mensaje = str(ctx.exception)
        self.assertIn("SUPABASE_EDGE_KEY", mensaje)
        self.assertIn("rls_edge.sql", mensaje)


class TestClaveRealtime(unittest.TestCase):
    """
    La senalizacion WebRTC es Broadcast puro: no toca ninguna tabla, asi que
    no debe llevar una clave privilegiada.
    """

    def test_prefiere_la_anon(self):
        self.assertEqual(
            clave_realtime("ANON", edge_key="EK", service_key="SK",
                           permitir_service=True),
            "ANON"
        )

    def test_la_anon_gana_incluso_sobre_la_restringida(self):
        clave = clave_realtime("ANON", edge_key="EK", service_key="",
                               permitir_service=True)
        self.assertNotEqual(clave, "EK")

    def test_sin_anon_cae_a_la_de_datos(self):
        """Fallback para no romper el streaming en instalaciones sin migrar."""
        self.assertEqual(
            clave_realtime("", edge_key="EK", service_key="",
                           permitir_service=True),
            "EK"
        )


class TestAvisoDeArranque(unittest.TestCase):

    def test_avisa_con_service_role(self):
        aviso = texto_aviso(SERVICE_ROLE)
        self.assertIsNotNone(aviso)
        self.assertIn("SALTA TODA LA RLS", aviso)
        self.assertIn("SUPABASE_EDGE_KEY", aviso)

    def test_no_avisa_con_clave_restringida(self):
        self.assertIsNone(texto_aviso(EDGE))


if __name__ == "__main__":
    unittest.main()
