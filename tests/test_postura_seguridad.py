"""
Tests del informe de postura de seguridad.

Lo que se protege: que una configuracion insegura no pase desapercibida, y
que en MODO_PRODUCCION el sistema se niegue a arrancar en vez de funcionar
durante meses con los ajustes de desarrollo.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.postura_seguridad import (
    evaluar, informe, bloqueantes, verificar,
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


def _ids(hallazgos):
    return {h.id for h in hallazgos}


def _por_id(hallazgos, hid):
    return [h for h in hallazgos if h.id == hid]


class TestConfiguracionSegura(unittest.TestCase):

    def test_sin_hallazgos(self):
        self.assertEqual(evaluar(modo_clave="edge", **SEGURA), [])

    def test_el_informe_lo_dice(self):
        texto = informe(evaluar(modo_clave="edge", **SEGURA))
        self.assertIn("sin hallazgos", texto)

    def test_arranca_incluso_en_produccion(self):
        puede, _ = verificar(modo_clave="edge", modo_produccion=True, **SEGURA)
        self.assertTrue(puede)


class TestCredencialesAdmin(unittest.TestCase):
    """C6: el hallazgo que motivo este modulo."""

    def test_contrasena_publicada_es_critica(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "admin_password": "admin123"})
        self.assertEqual(_por_id(h, "C6")[0].severidad, CRITICO)

    def test_todas_las_conocidas_son_criticas(self):
        for clave in CLAVES_CONOCIDAS:
            with self.subTest(clave=clave):
                h = evaluar(modo_clave="edge", **{**SEGURA, "admin_password": clave})
                self.assertEqual(_por_id(h, "C6")[0].severidad, CRITICO)

    def test_no_distingue_mayusculas(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "admin_password": "Admin123"})
        self.assertEqual(_por_id(h, "C6")[0].severidad, CRITICO)

    def test_una_contrasena_fuerte_sigue_siendo_hallazgo_menor(self):
        """
        Aunque sea fuerte, el edge no debe guardar credenciales de admin:
        ningun codigo suyo las usa.
        """
        h = evaluar(modo_clave="edge",
                    **{**SEGURA, "admin_password": "x9#Kq2!vLp7@Zr"})
        self.assertEqual(_por_id(h, "C6")[0].severidad, MEDIO)

    def test_solo_el_usuario_ya_es_hallazgo(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "admin_usuario": "admin"})
        self.assertEqual(len(_por_id(h, "C6")), 1)

    def test_sin_credenciales_no_hay_hallazgo(self):
        self.assertNotIn("C6", _ids(evaluar(modo_clave="edge", **SEGURA)))

    def test_espacios_no_cuentan_como_credencial(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "admin_password": "   "})
        self.assertNotIn("C6", _ids(h))


class TestOtrosHallazgos(unittest.TestCase):

    def test_service_role_es_critico(self):
        h = evaluar(modo_clave="service_role", **SEGURA)
        self.assertEqual(_por_id(h, "C3")[0].severidad, CRITICO)

    def test_capturas_publicas(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "storage_privado": False})
        self.assertEqual(_por_id(h, "C5")[0].severidad, ALTO)

    def test_webcam_sin_exigir_3d(self):
        h = evaluar(modo_clave="edge",
                    **{**SEGURA, "modo_camara": "simulada", "requerir_3d": False})
        self.assertEqual(_por_id(h, "C1")[0].severidad, ALTO)

    def test_webcam_exigiendo_3d_no_es_hallazgo(self):
        """Exigir 3D con webcam es seguro: simplemente no concede accesos."""
        h = evaluar(modo_clave="edge",
                    **{**SEGURA, "modo_camara": "simulada", "requerir_3d": True})
        self.assertNotIn("C1", _ids(h))

    def test_reenrolamiento_permanente(self):
        h = evaluar(modo_clave="edge",
                    **{**SEGURA, "permitir_reenrolamiento": True})
        self.assertEqual(_por_id(h, "C4")[0].severidad, ALTO)

    def test_sin_anon_key(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "anon_key": ""})
        self.assertIn(MEDIO, [x.severidad for x in _por_id(h, "C3")])

    def test_cleanup_en_el_dispositivo(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "cleanup_en_edge": True})
        self.assertTrue(_por_id(h, "C3"))

    def test_sin_firma_de_comandos(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "hmac_secret": ""})
        self.assertTrue(_por_id(h, "C4"))


class TestSenalizacionWebRTC(unittest.TestCase):
    """C2: quien puede pedir video en vivo."""

    def test_canal_publico_es_hallazgo_alto(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "canal_privado": False})
        self.assertEqual(_por_id(h, "C2")[0].severidad, ALTO)

    def test_canal_privado_no_es_hallazgo(self):
        self.assertNotIn("C2", _ids(evaluar(modo_clave="edge", **SEGURA)))

    def test_bloquea_el_arranque_en_produccion(self):
        puede, _ = verificar(modo_clave="edge", modo_produccion=True,
                             **{**SEGURA, "canal_privado": False})
        self.assertFalse(puede)


class TestModoProduccion(unittest.TestCase):
    """
    El punto del modo produccion: un sistema que no arranca se arregla hoy;
    un aviso se ignora durante meses.
    """

    def test_criticos_y_altos_bloquean(self):
        h = evaluar(modo_clave="service_role", **SEGURA)
        self.assertTrue(bloqueantes(h))

    def test_los_medios_no_bloquean(self):
        h = evaluar(modo_clave="edge", **{**SEGURA, "hmac_secret": ""})
        self.assertTrue(h, "deberia haber un hallazgo MEDIO")
        self.assertEqual(bloqueantes(h), [])

    def test_produccion_impide_arrancar_con_service_role(self):
        puede, _ = verificar(modo_clave="service_role", modo_produccion=True,
                             **SEGURA)
        self.assertFalse(puede)

    def test_desarrollo_arranca_igualmente(self):
        puede, hallazgos = verificar(modo_clave="service_role",
                                     modo_produccion=False, **SEGURA)
        self.assertTrue(puede)
        self.assertTrue(hallazgos, "pero debe informar de los hallazgos")

    def test_produccion_arranca_si_solo_hay_medios(self):
        puede, _ = verificar(modo_clave="edge", modo_produccion=True,
                             **{**SEGURA, "hmac_secret": ""})
        self.assertTrue(puede)


class TestInforme(unittest.TestCase):

    def test_ordena_por_gravedad(self):
        h = evaluar(modo_clave="service_role",
                    **{**SEGURA, "storage_privado": False, "hmac_secret": ""})
        severidades = [x.severidad for x in h]
        orden = {CRITICO: 0, ALTO: 1, MEDIO: 2}
        self.assertEqual(severidades, sorted(severidades, key=lambda s: orden[s]))

    def test_cada_hallazgo_trae_remedio(self):
        h = evaluar(modo_clave="service_role",
                    **{**SEGURA, "storage_privado": False,
                       "admin_password": "admin123"})
        for x in h:
            self.assertTrue(x.remedio, f"{x.id} sin remedio")
            self.assertTrue(x.titulo, f"{x.id} sin titulo")

    def test_el_informe_menciona_el_id_de_auditoria(self):
        """Poder cruzarlo con la auditoria importa para dar seguimiento."""
        texto = informe(evaluar(modo_clave="service_role", **SEGURA))
        self.assertIn("(C3)", texto)

    def test_avisa_de_lo_que_pasaria_en_produccion(self):
        texto = informe(evaluar(modo_clave="service_role", **SEGURA),
                        modo_produccion=False)
        self.assertIn("MODO_PRODUCCION=true", texto)


if __name__ == "__main__":
    unittest.main()
