"""
Tests del acceso a Storage (hallazgo C5).

Lo que se protege: que las imagenes biometricas dejen de servirse por URLs
publicas sin caducidad, y que la caducidad de las firmadas no deje huecos en
el historial.
"""

import sys
import os
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import almacenamiento


class AlmacenFalso:
    """Imita storage.from_(bucket) registrando como se le llamo."""

    def __init__(self, respuesta_firma=None, falla=False):
        self.respuesta_firma = respuesta_firma
        self.falla = falla
        self.llamadas_publicas = []
        self.llamadas_firmadas = []

    def get_public_url(self, ruta):
        self.llamadas_publicas.append(ruta)
        return f"https://proyecto.supabase.co/storage/v1/object/public/capturas/{ruta}"

    def create_signed_url(self, ruta, validez):
        self.llamadas_firmadas.append((ruta, validez))
        if self.falla:
            raise RuntimeError("bucket no encontrado")
        return self.respuesta_firma


class ClienteFalso:
    def __init__(self, almacen):
        self._almacen = almacen
        self.storage = self

    def from_(self, bucket):
        self.bucket = bucket
        return self._almacen


class TestExtraerUrlFirmada(unittest.TestCase):
    """
    La clave del dict cambia segun la version de storage3. Equivocarse la
    dejaria en None y las fotos se quedarian sin URL EN SILENCIO.
    """

    def test_acepta_las_variantes_conocidas(self):
        for clave in ("signedURL", "signedUrl", "signed_url", "signedurl"):
            with self.subTest(clave=clave):
                self.assertEqual(
                    almacenamiento.extraer_url_firmada({clave: "/firmada?token=x"}),
                    "/firmada?token=x",
                )

    def test_acepta_una_cadena_directa(self):
        self.assertEqual(almacenamiento.extraer_url_firmada("/x"), "/x")

    def test_respuesta_vacia_da_none(self):
        self.assertIsNone(almacenamiento.extraer_url_firmada({}))
        self.assertIsNone(almacenamiento.extraer_url_firmada(None))
        self.assertIsNone(almacenamiento.extraer_url_firmada(""))

    def test_clave_desconocida_da_none_y_no_explota(self):
        self.assertIsNone(almacenamiento.extraer_url_firmada({"otra": "/x"}))


class TestModoPublico(unittest.TestCase):
    """Comportamiento heredado, que es el problema de C5."""

    def test_devuelve_url_publica(self):
        almacen = AlmacenFalso()
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", False):
            url = almacenamiento.url_de(ClienteFalso(almacen), "foto.jpg")
        self.assertIn("/public/", url)
        self.assertEqual(almacen.llamadas_publicas, ["foto.jpg"])
        self.assertEqual(almacen.llamadas_firmadas, [])

    def test_avisa_al_arrancar(self):
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", False):
            aviso = almacenamiento.texto_aviso()
        self.assertIsNotNone(aviso)
        self.assertIn("PUBLICO", aviso)
        self.assertIn("STORAGE_PRIVADO=true", aviso)


class TestModoPrivado(unittest.TestCase):

    def test_devuelve_url_firmada_y_no_publica(self):
        almacen = AlmacenFalso({"signedURL": "/firmada?token=abc"})
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", True):
            url = almacenamiento.url_de(ClienteFalso(almacen), "foto.jpg")
        self.assertEqual(url, "/firmada?token=abc")
        self.assertEqual(almacen.llamadas_publicas, [],
                         "en modo privado NO debe generarse ninguna URL publica")

    def test_no_avisa(self):
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", True):
            self.assertIsNone(almacenamiento.texto_aviso())

    def test_un_fallo_al_firmar_devuelve_none_y_no_propaga(self):
        """
        Si no se puede firmar, mejor quedarse sin foto que tumbar el hilo de
        sync o caer a una URL publica por detras.
        """
        almacen = AlmacenFalso(falla=True)
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", True):
            url = almacenamiento.url_de(ClienteFalso(almacen), "foto.jpg")
        self.assertIsNone(url)
        self.assertEqual(almacen.llamadas_publicas, [])

    def test_usa_la_validez_pedida(self):
        almacen = AlmacenFalso({"signedURL": "/x"})
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", True):
            almacenamiento.url_de(ClienteFalso(almacen), "foto.jpg", 120)
        self.assertEqual(almacen.llamadas_firmadas, [("foto.jpg", 120)])


class TestCaducidad(unittest.TestCase):

    def test_las_fotos_sobreviven_a_su_retencion(self):
        """
        Si la URL caducara ANTES de que la limpieza borre el registro, el
        historial mostraria huecos durante ese margen.
        """
        with mock.patch.object(almacenamiento, "DIAS_RETENCION", 30):
            segundos = almacenamiento.validez_fotos_segundos()
        self.assertGreater(segundos, 30 * 24 * 3600)

    def test_escala_con_la_retencion_configurada(self):
        with mock.patch.object(almacenamiento, "DIAS_RETENCION", 7):
            corta = almacenamiento.validez_fotos_segundos()
        with mock.patch.object(almacenamiento, "DIAS_RETENCION", 90):
            larga = almacenamiento.validez_fotos_segundos()
        self.assertLess(corta, larga)

    def test_el_preview_dura_mas_que_el_heartbeat(self):
        """
        El heartbeat renueva la URL cada 30s; si caducara antes, el preview
        parpadearia.
        """
        self.assertGreater(almacenamiento.VALIDEZ_PREVIEW, 30 * 10)


class TestUrlPreview(unittest.TestCase):

    def test_firma_el_fichero_de_preview(self):
        almacen = AlmacenFalso({"signedURL": "/preview?token=x"})
        with mock.patch.object(almacenamiento, "STORAGE_PRIVADO", True):
            url = almacenamiento.url_preview(ClienteFalso(almacen))
        self.assertEqual(url, "/preview?token=x")
        ruta, validez = almacen.llamadas_firmadas[0]
        self.assertEqual(ruta, almacenamiento.PREVIEW)
        self.assertEqual(validez, almacenamiento.VALIDEZ_PREVIEW)


class TestHeartbeatPublicaElPreview(unittest.TestCase):
    """
    Con el bucket privado el frontend ya no puede construir la URL del
    preview: tiene que leerla de estado_sistema.
    """

    def test_la_camara_activa_lleva_preview_url(self):
        from backend.heartbeat import _construir_camaras
        camaras = _construir_camaras("entrada_principal", "3D", "realsense",
                                     preview_url="/firmada?token=x")
        activa = [c for c in camaras if c["activa"]]
        self.assertEqual(len(activa), 1)
        self.assertEqual(activa[0]["preview_url"], "/firmada?token=x")

    def test_las_inactivas_no_llevan_url(self):
        from backend.heartbeat import _construir_camaras
        camaras = _construir_camaras("entrada_principal", "3D", "realsense",
                                     preview_url="/firmada?token=x")
        for cam in camaras:
            if not cam["activa"]:
                self.assertNotIn("preview_url", cam)

    def test_sin_url_no_se_anade_la_clave(self):
        """Si no se pudo firmar, mejor no publicar una clave vacia."""
        from backend.heartbeat import _construir_camaras
        camaras = _construir_camaras("entrada_principal", "3D", "realsense",
                                     preview_url=None)
        for cam in camaras:
            self.assertNotIn("preview_url", cam)


if __name__ == "__main__":
    unittest.main()
