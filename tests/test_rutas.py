"""
Tests de config/rutas.py.

Lo que se protege aqui: que el paso a ejecutable no cambie NADA para quien
sigue arrancando con `python iniciar.py`, y que el ejecutable nunca intente
escribir dentro de su propia carpeta de instalacion (Program Files no es
escribible para un usuario normal).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import rutas

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSinEmpaquetar(unittest.TestCase):

    def test_todo_queda_en_la_raiz_del_repo(self):
        recursos, datos = rutas.resolver(False, None, {}, RAIZ)
        self.assertEqual(recursos, RAIZ)
        self.assertEqual(datos, RAIZ)

    def test_las_rutas_de_siempre_no_cambian(self):
        """Mismo .env, mismas capturas, mismo modelo que antes del cambio."""
        self.assertFalse(rutas.EMPAQUETADO)
        if os.environ.get("DEPTHGUARD_DATOS"):
            self.skipTest("DEPTHGUARD_DATOS esta definido en este entorno")
        self.assertEqual(rutas.RUTA_ENV, os.path.join(RAIZ, ".env"))
        self.assertEqual(rutas.CAPTURAS_DIR, os.path.join(RAIZ, "capturas"))
        self.assertEqual(rutas.DIR_MODELOS,
                         os.path.join(RAIZ, "scripts", "_modelos"))


class TestEmpaquetado(unittest.TestCase):

    def test_datos_en_programdata_y_no_junto_al_ejecutable(self):
        entorno = {"PROGRAMDATA": os.path.join("C:", os.sep, "ProgramData")}
        recursos, datos = rutas.resolver(True, "/interno", entorno, RAIZ)
        self.assertEqual(recursos, "/interno")
        self.assertEqual(datos, os.path.join(entorno["PROGRAMDATA"], "DepthGuard"))
        self.assertNotEqual(datos, recursos)

    def test_sin_programdata_no_cae_en_la_carpeta_del_programa(self):
        """Fuera de Windows no hay PROGRAMDATA: debe caer en el perfil."""
        _, datos = rutas.resolver(True, "/interno", {}, RAIZ)
        self.assertTrue(datos.startswith(os.path.expanduser("~")))
        self.assertTrue(datos.endswith("DepthGuard"))


class TestCarpetaForzada(unittest.TestCase):

    def test_la_variable_gana_en_ambos_modos(self):
        entorno = {"DEPTHGUARD_DATOS": "/datos/prueba",
                   "PROGRAMDATA": "/otra"}
        for empaquetado in (False, True):
            _, datos = rutas.resolver(empaquetado, "/interno", entorno, RAIZ)
            self.assertEqual(datos, os.path.abspath("/datos/prueba"))

    def test_vacia_se_ignora(self):
        _, datos = rutas.resolver(False, None, {"DEPTHGUARD_DATOS": "  "}, RAIZ)
        self.assertEqual(datos, RAIZ)


if __name__ == "__main__":
    unittest.main()
