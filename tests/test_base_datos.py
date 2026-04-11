"""Tests para la base de datos."""

import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Sobreescribir config antes de importar BaseDatos
import config.settings as settings


class TestBaseDatos(unittest.TestCase):

    def setUp(self):
        """Crear DB temporal para cada test."""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        settings.DB_PATH = self.tmp.name
        # Reimport to get a fresh BaseDatos with the new path
        import importlib
        import backend.base_datos
        importlib.reload(backend.base_datos)
        from backend.base_datos import BaseDatos
        self.db = BaseDatos()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_admin_por_defecto_existe(self):
        """El admin por defecto debe crearse automáticamente."""
        admin = self.db.verificar_admin(
            settings.ADMIN_USUARIO, settings.ADMIN_PASSWORD
        )
        self.assertIsNotNone(admin)

    def test_admin_credenciales_incorrectas(self):
        """Credenciales incorrectas deben retornar None."""
        admin = self.db.verificar_admin("admin", "wrong_password")
        self.assertIsNone(admin)

    def test_crear_admin_adicional(self):
        """Debe poder crear y autenticar un admin adicional."""
        self.db.crear_admin("nuevo_admin", "clave_segura")
        admin = self.db.verificar_admin("nuevo_admin", "clave_segura")
        self.assertIsNotNone(admin)

    def test_insertar_historial(self):
        """Insertar y recuperar historial."""
        self.db.insertar_historial(
            "FRAUDE", "", "/capturas/test.jpg", 0, {"varianza": 0.5}
        )
        historial = self.db.obtener_historial(10)
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["estado"], "FRAUDE")

    def test_historial_orden_descendente(self):
        """El historial debe venir del más reciente al más antiguo."""
        self.db.insertar_historial("PERMITIDO", "Juan", "", 95.0, {})
        self.db.insertar_historial("FRAUDE", "", "", 0, {})
        historial = self.db.obtener_historial(10)
        self.assertEqual(historial[0]["estado"], "FRAUDE")
        self.assertEqual(historial[1]["estado"], "PERMITIDO")

    def test_suscripciones_push(self):
        """Guardar y recuperar suscripciones push."""
        import json
        sub = {"endpoint": "https://example.com/push", "keys": {}}
        self.db.guardar_suscripcion_push(json.dumps(sub))
        subs = self.db.obtener_suscripciones_push()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["endpoint"], "https://example.com/push")


if __name__ == "__main__":
    unittest.main()
