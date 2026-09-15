"""
Tests del informe de postura de seguridad.

Lo que se protege: que una configuracion insegura no pase desapercibida, y que
en MODO_PRODUCCION el sistema se niegue a arrancar en vez de funcionar durante
meses con los ajustes de desarrollo.

Este fichero tenia 30 tests para un modulo de 229 lineas que clasifica ajustes e
imprime un informe: era la proporcion mas alta de la suite para el codigo menos
arriesgado. La cobertura se conserva entera —los mismos casos se siguen
comprobando— pero once funciones que solo cambiaban un ajuste y miraban una
severidad son ahora una tabla. Menos ruido que mantener, y cuando falla dice que
fila fallo. Lo que se elimino de verdad es el formato del informe (orden de las
lineas, texto exacto), que no tiene consecuencias.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.postura_seguridad import (
    evaluar, informe, verificar,
    CRITICO, ALTO, MEDIO, CLAVES_CONOCIDAS,
)


# Configuracion objetivo de un despliegue real
SEGURA = {
    "modo_camara": "realsense",
    "requerir_3d": True,
    "anon_key": "ANON",
    "cleanup_en_edge": False,
    "storage_privado": True,
    "permitir_reenrolamiento": False,
    "hmac_secret": "SECRETO",
    "admin_password": "",
    "admin_usuario": "",
    "canal_privado": True,
}


def _evaluar(modo_clave="edge", **cambios):
    return evaluar(modo_clave=modo_clave, **{**SEGURA, **cambios})


def _por_id(hallazgos, hid):
    return [h for h in hallazgos if h.id == hid]


class TestConfiguracionSegura(unittest.TestCase):

    def test_no_produce_hallazgos_y_arranca_en_produccion(self):
        # Si esto se rompiera, un despliegue CORRECTO no podria arrancar, que es
        # el fallo mas caro de este modulo: bloquea a quien lo hizo bien.
        hallazgos = _evaluar()
        self.assertEqual(hallazgos, [])
        puede, _ = verificar(modo_clave="edge", modo_produccion=True, **SEGURA)
        self.assertTrue(puede)


class TestDeteccionDeHallazgos(unittest.TestCase):
    """
    Cada ajuste insegura produce su hallazgo, con la severidad que le toca.

    Tabla en vez de una funcion por caso: eran once tests identicos salvo un
    ajuste y una severidad.
    """

    CASOS = [
        # (descripcion, cambios, modo_clave, id esperado, severidad esperada)
        ("clave service_role en el dispositivo",
         {}, "service_role", "C3", CRITICO),
        ("capturas biometricas publicas",
         {"storage_privado": False}, "edge", "C5", ALTO),
        ("webcam concediendo accesos sin 3D",
         {"modo_camara": "simulada", "requerir_3d": False}, "edge", "C1", ALTO),
        ("canal WebRTC publico",
         {"canal_privado": False}, "edge", "C2", ALTO),
        ("reenrolamiento permanente",
         {"permitir_reenrolamiento": True}, "edge", "C4", ALTO),
        ("sin clave anon",
         {"anon_key": ""}, "edge", "C3", MEDIO),
        ("comandos de enrolamiento sin firmar",
         {"hmac_secret": ""}, "edge", "C4", None),
        ("borrado del historico desde el dispositivo",
         {"cleanup_en_edge": True}, "edge", "C3", None),
        ("credenciales de admin en el .env",
         {"admin_usuario": "admin"}, "edge", "C6", None),
    ]

    def test_cada_ajuste_insegura_se_detecta(self):
        for desc, cambios, modo, hid, severidad in self.CASOS:
            with self.subTest(desc):
                hallazgos = _evaluar(modo_clave=modo, **cambios)
                encontrados = _por_id(hallazgos, hid)
                self.assertTrue(
                    encontrados,
                    f"'{desc}' deberia producir el hallazgo {hid} y no lo hace"
                )
                if severidad is not None:
                    self.assertIn(severidad, [h.severidad for h in encontrados])

    def test_exigir_3d_con_webcam_no_es_hallazgo(self):
        # El caso contrario importa: con REQUERIR_CAMARA_3D=true una webcam es
        # segura porque simplemente no concede accesos. Avisar ahi seria ruido,
        # y el ruido hace que se ignore el informe entero.
        hallazgos = _evaluar(modo_camara="simulada", requerir_3d=True)
        self.assertEqual(_por_id(hallazgos, "C1"), [])


class TestCredencialesAdmin(unittest.TestCase):
    """C6: el hallazgo que motivo este modulo."""

    def test_las_contrasenas_conocidas_son_criticas(self):
        # Cubre la lista negra entera y que no distingue mayusculas: una clave
        # publicada sigue siendo publicada escrita como sea.
        for clave in CLAVES_CONOCIDAS:
            for variante in (clave, clave.upper(), clave.capitalize()):
                with self.subTest(variante):
                    hallazgos = _evaluar(admin_usuario="admin",
                                         admin_password=variante)
                    self.assertIn(
                        CRITICO, [h.severidad for h in _por_id(hallazgos, "C6")]
                    )

    def test_una_contrasena_fuerte_sigue_siendo_hallazgo_pero_menor(self):
        # Tener credenciales en el .env del dispositivo es un problema aunque la
        # clave sea buena; lo que cambia es la urgencia, no la existencia.
        hallazgos = _evaluar(admin_usuario="admin",
                             admin_password="xK9#mQ2$vL7pR4wZ")
        c6 = _por_id(hallazgos, "C6")
        self.assertTrue(c6)
        self.assertNotIn(CRITICO, [h.severidad for h in c6])

    def test_sin_credenciales_no_hay_hallazgo(self):
        self.assertEqual(_por_id(_evaluar(), "C6"), [])


class TestModoProduccion(unittest.TestCase):
    """El contrato del modulo: que impide arrancar y que no."""

    def test_criticos_y_altos_bloquean(self):
        for desc, cambios, modo in (
            ("critico: service_role", {}, "service_role"),
            ("alto: canal WebRTC publico", {"canal_privado": False}, "edge"),
            ("alto: capturas publicas", {"storage_privado": False}, "edge"),
        ):
            with self.subTest(desc):
                puede, _ = verificar(
                    modo_clave=modo, modo_produccion=True,
                    **{**SEGURA, **cambios}
                )
                self.assertFalse(puede, f"{desc} deberia impedir el arranque")

    def test_los_medios_no_bloquean(self):
        # Un MEDIO avisa pero no deja el sistema parado: bloquear por todo
        # acabaria con alguien poniendo MODO_PRODUCCION=false para siempre.
        puede, _ = verificar(modo_clave="edge", modo_produccion=True,
                             **{**SEGURA, "hmac_secret": ""})
        self.assertTrue(puede)

    def test_en_desarrollo_nada_bloquea(self):
        puede, _ = verificar(modo_clave="service_role", modo_produccion=False,
                             **SEGURA)
        self.assertTrue(puede)


class TestInforme(unittest.TestCase):

    def test_cada_hallazgo_trae_su_remedio(self):
        # Un hallazgo sin remedio no sirve de nada a quien lee el log: sabe que
        # algo esta mal y no que hacer. Se comprueba sobre TODOS a la vez.
        hallazgos = evaluar(
            modo_clave="service_role",
            **{**SEGURA, "modo_camara": "simulada", "requerir_3d": False,
               "storage_privado": False, "canal_privado": False,
               "permitir_reenrolamiento": True, "hmac_secret": "",
               "cleanup_en_edge": True, "anon_key": "",
               "admin_usuario": "admin", "admin_password": "admin123"}
        )
        self.assertGreater(len(hallazgos), 5)
        texto = informe(hallazgos)
        for h in hallazgos:
            with self.subTest(h.id):
                self.assertTrue(h.remedio.strip(),
                                f"{h.id} no explica como arreglarlo")
                self.assertIn(h.id, texto)


if __name__ == "__main__":
    unittest.main()
