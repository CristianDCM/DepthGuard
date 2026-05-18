"""Tests para EstadoRegistro thread-safe."""

import sys
import os
import unittest
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor_ia.estado_registro import EstadoRegistro, ANGULOS_REGISTRO


class TestEstadoRegistro(unittest.TestCase):

    def test_estado_inicial(self):
        estado = EstadoRegistro()
        self.assertFalse(estado.activo)
        self.assertEqual(estado.nombre, "")
        self.assertEqual(estado.embeddings, [])
        self.assertEqual(estado.paso, 0)
        self.assertFalse(estado.completado)

    def test_iniciar_registro(self):
        estado = EstadoRegistro()
        estado.iniciar("Carlos")
        self.assertTrue(estado.activo)
        self.assertEqual(estado.nombre, "Carlos")
        self.assertEqual(estado.angulo_solicitado, "frontal")
        self.assertEqual(estado.angulos_capturados, [])

    def test_completar_registro(self):
        estado = EstadoRegistro()
        estado.iniciar("Ana")
        estado.completar({"id": 1, "nombre": "Ana"})
        self.assertFalse(estado.activo)
        snap = estado.obtener_estado()
        self.assertTrue(snap["completado"])
        self.assertEqual(snap["datos"]["nombre"], "Ana")

    def test_obtener_estado_limpia_completado(self):
        estado = EstadoRegistro()
        estado.completar({"id": 1})
        snap1 = estado.obtener_estado()
        self.assertTrue(snap1["completado"])
        snap2 = estado.obtener_estado()
        self.assertFalse(snap2["completado"])

    def test_agregar_embedding(self):
        estado = EstadoRegistro()
        estado.agregar_embedding([0.1, 0.2])
        estado.agregar_embedding([0.3, 0.4])
        self.assertEqual(len(estado.embeddings), 2)

    def test_registrar_captura_avanza_angulo(self):
        """Registrar una captura avanza al siguiente ángulo."""
        estado = EstadoRegistro()
        estado.iniciar("Test")

        self.assertEqual(estado.angulo_solicitado, "frontal")
        estado.registrar_captura([0.1, 0.2], "frontal")

        self.assertEqual(estado.paso, 1)
        self.assertEqual(estado.angulo_solicitado, "izquierda")
        self.assertEqual(estado.angulos_capturados, ["frontal"])

    def test_secuencia_completa_angulos(self):
        """Verificar que la secuencia completa de 5 ángulos funciona."""
        estado = EstadoRegistro()
        estado.iniciar("Test")

        for i, angulo in enumerate(ANGULOS_REGISTRO):
            self.assertEqual(estado.angulo_solicitado, angulo)
            estado.registrar_captura([float(i)] * 128, angulo)
            # Necesitamos saltar el cooldown para tests
            estado._ultimo_captura = 0

        self.assertEqual(estado.paso, 5)
        self.assertEqual(len(estado.embeddings), 5)
        self.assertEqual(estado.angulos_capturados, list(ANGULOS_REGISTRO))

    def test_puede_capturar_cooldown(self):
        """Verifica que hay cooldown entre capturas."""
        estado = EstadoRegistro()
        estado.iniciar("Test")

        # Primera captura siempre puede
        self.assertTrue(estado.puede_capturar())

        estado.registrar_captura([0.1], "frontal")

        # Justo después no debería poder
        self.assertFalse(estado.puede_capturar())

    def test_obtener_estado_incluye_angulos(self):
        """El estado debe incluir información de ángulos."""
        estado = EstadoRegistro()
        estado.iniciar("Test")
        estado.registrar_captura([0.1], "frontal")
        estado._ultimo_captura = 0  # reset cooldown

        snap = estado.obtener_estado()
        self.assertEqual(snap["angulo_solicitado"], "izquierda")
        self.assertEqual(snap["angulos_capturados"], ["frontal"])
        self.assertEqual(snap["paso"], 1)

    def test_concurrencia(self):
        """Múltiples hilos escribiendo no deben crashear."""
        estado = EstadoRegistro()
        errores = []

        def escribir(n):
            try:
                for i in range(100):
                    estado.paso = i
                    estado.agregar_embedding([n, i])
            except Exception as e:
                errores.append(e)

        hilos = [threading.Thread(target=escribir, args=(i,))
                 for i in range(5)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(len(errores), 0)
        self.assertEqual(len(estado.embeddings), 500)


if __name__ == "__main__":
    unittest.main()
