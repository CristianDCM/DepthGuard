"""
Tests de autoprueba.py (`iniciar.py --autoprueba`).

Lo que se protege aqui: que la autoprueba FALLE cuando falta una pieza (es la
puerta del build del ejecutable), y que corra sin .env ni Supabase, porque en
el build de GitHub no hay ninguno de los dos.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import autoprueba

# onnxruntime es opcional en requirements.txt; en el build siempre esta.
_MODULOS = ("cv2", "mediapipe", "face_recognition", "aiortc", "av",
            "pyrealsense2", "onnxruntime", "supabase")
_ENTORNO_COMPLETO = all(importlib.util.find_spec(m) for m in _MODULOS)


def _ok():
    return "bien"


class TestResultado(unittest.TestCase):

    def _ejecutar(self, comprobaciones):
        lineas = []
        return autoprueba.ejecutar(comprobaciones, lineas.append), lineas

    def test_todo_bien_sale_con_0(self):
        codigo, lineas = self._ejecutar((("a", _ok), ("b", _ok)))
        self.assertEqual(codigo, 0)
        self.assertIn("AUTOPRUEBA OK", lineas[-1])

    def test_un_error_sale_con_1_y_sigue_con_el_resto(self):
        def rota():
            raise ImportError("falta una DLL")
        codigo, lineas = self._ejecutar((("rota", rota), ("b", _ok)))
        self.assertEqual(codigo, 1)
        self.assertTrue(any("FALLO" in l and "falta una DLL" in l for l in lineas))
        self.assertTrue(any("[OK" in l and "b:" in l for l in lineas))

    def test_un_quit_cuenta_como_fallo(self):
        """face_recognition sin modelos llama a quit(): codigo 0, pero es un fallo."""
        def sale():
            raise SystemExit(0)
        codigo, _ = self._ejecutar((("sale", sale),))
        self.assertEqual(codigo, 1)


@unittest.skipUnless(_ENTORNO_COMPLETO, "faltan librerias del build en este entorno")
class TestDeVerdad(unittest.TestCase):

    def test_iniciar_con_autoprueba_pasa_sin_env(self):
        """
        Sin .env, `python iniciar.py` sale con error (no hay SUPABASE_URL).
        Con --autoprueba no debe llegar a ese punto.
        """
        with tempfile.TemporaryDirectory() as datos:
            entorno = dict(os.environ, DEPTHGUARD_DATOS=datos)
            r = subprocess.run(
                [sys.executable, os.path.join(RAIZ, "iniciar.py"), "--autoprueba"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=entorno, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AUTOPRUEBA OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
