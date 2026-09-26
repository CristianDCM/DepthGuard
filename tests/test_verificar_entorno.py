"""
Tests de empaquetado/verificar_entorno.py.

Lo que se protege aqui: que el verificador de verdad PARE el build cuando el
entorno no es el probado, y que no lo pare por el unico aviso conocido e
inofensivo (face-recognition pidiendo `dlib`, que cubre dlib-bin).
"""

import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "empaquetado"))

import verificar_entorno as v


class TestLock(unittest.TestCase):

    def test_el_lock_del_repo_se_lee_entero_y_con_un_solo_opencv(self):
        with open(v.LOCK, encoding="utf-8") as f:
            esperadas = v.leer_lock(f)
        self.assertIn("mediapipe", esperadas)
        self.assertEqual(v.errores_opencv(esperadas), [])

    def test_setuptools_fijado_con_pkg_resources(self):
        """
        face_recognition_models importa pkg_resources, que setuptools quito en
        la 82. Si alguien sube setuptools en el lock, el ejecutable arranca sin
        reconocimiento facial.
        """
        with open(v.LOCK, encoding="utf-8") as f:
            esperadas = v.leer_lock(f)
        self.assertIn("setuptools", esperadas)
        self.assertLess(int(esperadas["setuptools"].split(".")[0]), 82)

    def test_nombres_normalizados(self):
        esperadas = v.leer_lock(["Pillow==1", "face_recognition_models==2"])
        self.assertEqual(esperadas, {"pillow": "1", "face-recognition-models": "2"})

    def test_ignora_comentarios_y_vacias(self):
        self.assertEqual(v.leer_lock(["# x", "", "a==1  # nota"]), {"a": "1"})

    def test_rechaza_versiones_no_exactas(self):
        with self.assertRaises(ValueError):
            v.leer_lock(["numpy>=2"])


class TestComparar(unittest.TestCase):

    def test_todo_igual(self):
        self.assertEqual(v.comparar({"a": "1"}, {"a": "1", "extra": "9"}), [])

    def test_falta_y_version_distinta(self):
        errores = v.comparar({"a": "1", "b": "2"}, {"b": "3"})
        self.assertEqual(len(errores), 2)
        self.assertIn("Falta a==1", errores)


class TestOpenCV(unittest.TestCase):

    def test_dos_opencv_es_error(self):
        self.assertEqual(len(v.errores_opencv(
            {"opencv-python": "5", "opencv-contrib-python": "5"})), 1)

    def test_ninguno_es_error(self):
        self.assertEqual(len(v.errores_opencv({"numpy": "2"})), 1)


class TestPipCheck(unittest.TestCase):

    def test_tolera_solo_dlib_de_face_recognition(self):
        salida = ("face-recognition 1.3.0 requires dlib, which is not installed.\n"
                  "mediapipe 0.10.14 requires jax, which is not installed.\n")
        self.assertEqual(v.filtrar_pip_check(salida),
                         ["mediapipe 0.10.14 requires jax, which is not installed."])

    def test_sin_problemas(self):
        self.assertEqual(v.filtrar_pip_check("No broken requirements found.\n"), [])


class TestImportacion(unittest.TestCase):

    def test_un_quit_al_importar_cuenta_como_fallo(self):
        """
        face_recognition sin sus modelos llama a quit() (codigo 0) en vez de
        lanzar un error. Eso NO puede pasar por un entorno valido.
        """
        def importar(nombre):
            if nombre == "face_recognition":
                raise SystemExit(0)
        errores = v.errores_importacion(["numpy", "face_recognition"], importar)
        self.assertEqual(len(errores), 1)
        self.assertIn("face_recognition", errores[0])

    def test_error_normal_de_importacion(self):
        def importar(nombre):
            raise ImportError("libusb-1.0.so.0")
        self.assertEqual(len(v.errores_importacion(["pyrealsense2"], importar)), 1)


if __name__ == "__main__":
    unittest.main()
