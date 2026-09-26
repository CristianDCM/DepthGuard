"""
Que DepthGuard no quede "en linea" sin pipeline.

Visto en la primera prueba del ejecutable: con MOTOR_EMBEDDING=onnx y sin el
modelo, el pipeline murio al ver el primer rostro y el proceso siguio vivo
(heartbeat, WebRTC y comandos funcionando), asi que la web mostraba el sistema
en linea mientras no se reconocia a nadie.

Se protege aqui:
  - que el pipeline NO se trague sus errores,
  - que el hilo recuerde si termino por error o por 'q',
  - que con el modelo ausente DepthGuard ni siquiera arranque.
"""

import os
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from motor_ia.hilo_pipeline import HiloPipeline


def _correr(objetivo):
    hilo = HiloPipeline(objetivo)
    hilo.start()
    hilo.join(timeout=10)
    return hilo


class TestHiloPipeline(unittest.TestCase):

    def test_termina_bien_sin_error(self):
        self.assertIsNone(_correr(lambda: None).error)

    def test_recuerda_el_error(self):
        def falla():
            raise FileNotFoundError("sin modelo")
        hilo = _correr(falla)
        self.assertIsInstance(hilo.error, FileNotFoundError)

    def test_un_quit_cuenta_como_error_y_no_como_q(self):
        def sale():
            raise SystemExit(0)
        self.assertIsInstance(_correr(sale).error, SystemExit)

    def test_pasa_los_argumentos(self):
        recibido = {}
        def objetivo(a, b, c=None):
            recibido.update(a=a, b=b, c=c)
        hilo = HiloPipeline(objetivo, 1, 2, c=3)
        hilo.start()
        hilo.join(timeout=10)
        self.assertEqual(recibido, {"a": 1, "b": 2, "c": 3})


class TestPipelineNoSeTragaErrores(unittest.TestCase):

    def test_un_error_en_el_bucle_llega_a_quien_lo_llama(self):
        import motor_ia.pipeline as pipeline
        from motor_ia.estado_registro import EstadoRegistro

        class _CamaraRota:
            profundidad_real = False
            def conectar(self): pass
            def obtener_frames(self):
                raise RuntimeError("camara desconectada")
            def cerrar(self): pass

        with mock.patch.object(pipeline, "crear_camara", lambda: _CamaraRota()), \
             mock.patch.object(pipeline, "_cargar_usuarios_supabase", lambda: []), \
             mock.patch.object(pipeline, "mostrar_preview", lambda v: False), \
             mock.patch.object(pipeline, "subir_snapshot", lambda f: None), \
             mock.patch.object(pipeline, "obtener_cliente", lambda: None):
            with self.assertRaises(RuntimeError):
                pipeline.ejecutar_pipeline(queue.Queue(), EstadoRegistro())


class TestMensajeModeloAusente(unittest.TestCase):

    def test_sin_empaquetar_apunta_al_script(self):
        from motor_ia.reconocimiento.motor_onnx import mensaje_modelo_ausente
        self.assertIn("descargar_modelo.py", mensaje_modelo_ausente("/x.onnx"))

    def test_empaquetado_dice_en_que_carpeta_ponerlo(self):
        """El ejecutable no tiene Python: mandar a correr un script no sirve."""
        from config import rutas
        from motor_ia.reconocimiento.motor_onnx import mensaje_modelo_ausente
        with mock.patch.object(rutas, "EMPAQUETADO", True), \
             mock.patch.object(rutas, "DIR_MODELOS", r"C:\ProgramData\DepthGuard\modelos"):
            texto = mensaje_modelo_ausente("/x.onnx")
        self.assertNotIn("python", texto)
        self.assertIn(r"C:\ProgramData\DepthGuard\modelos", texto)
        self.assertIn("RUTA_MODELO_ONNX", texto)


class TestArranqueSinModelo(unittest.TestCase):

    def test_no_arranca_si_falta_el_modelo_onnx(self):
        """
        Debe negarse ANTES de crear el cliente de Supabase o levantar hilos:
        el .env apunta a un Supabase que no existe y aun asi la salida tiene
        que ser el aviso del modelo, no un error de red.
        """
        with tempfile.TemporaryDirectory() as datos:
            with open(os.path.join(datos, ".env"), "w", encoding="utf-8") as f:
                f.write("SUPABASE_URL=https://no-existe.invalid\n"
                        "SUPABASE_EDGE_KEY=clave-de-prueba\n"
                        "MOTOR_EMBEDDING=onnx\n"
                        f"RUTA_MODELO_ONNX={os.path.join(datos, 'falta.onnx')}\n")
            r = subprocess.run(
                [sys.executable, os.path.join(RAIZ, "iniciar.py")],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300,
                env=dict(os.environ, DEPTHGUARD_DATOS=datos))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("No encuentro el modelo ONNX", r.stdout)
        self.assertNotIn("Pipeline IA activo", r.stdout)


if __name__ == "__main__":
    unittest.main()
