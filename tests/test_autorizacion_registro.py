"""
Tests de autorizacion de comandos de registro (hallazgo C4).

El escenario que da sentido al modulo esta en TestVectorDeSuplantacion: un
atacante que puede escribir en `comandos_edge` intentando sobrescribir la
biometria de un administrador con su propia cara.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.autorizacion_registro import (
    validar_comando_registro, firma_esperada, tiene_biometria,
    FALTA_USUARIO_ID, FIRMA_INVALIDA, USUARIO_NO_EXISTE,
    NOMBRE_INCONSISTENTE, REENROLAMIENTO_NO_AUTORIZADO,
)

SECRETO = "secreto-de-servidor"


def _comando(**kwargs):
    base = {
        "id": "cmd-1",
        "tipo": "INICIAR_REGISTRO",
        "usuario_id": "u-nuevo",
        "nombre": "Ana Perez",
    }
    base.update(kwargs)
    return base


def _usuario(nombre="Ana Perez", num_angulos=0, uid="u-nuevo"):
    return {
        "id": uid,
        "nombre": nombre,
        "num_angulos": num_angulos,
        "embeddings_json": [[0.0] * 128] * num_angulos,
        "activo": True,
    }


class TestAltaLegitima(unittest.TestCase):

    def test_usuario_nuevo_sin_biometria_se_autoriza(self):
        ok, motivo, _ = validar_comando_registro(_comando(), _usuario())
        self.assertTrue(ok, motivo)

    def test_comando_sin_nombre_usa_el_de_la_bd(self):
        """
        Si el comando no dice nombre no hay nada que contrastar, pero el
        contexto debe traer el nombre AUTORITATIVO de la base de datos.
        """
        cmd = _comando()
        del cmd["nombre"]
        ok, _, ctx = validar_comando_registro(cmd, _usuario())
        self.assertTrue(ok)
        self.assertEqual(ctx["nombre_db"], "Ana Perez")

    def test_espacios_alrededor_del_nombre_no_rompen_el_alta(self):
        ok, motivo, _ = validar_comando_registro(
            _comando(nombre="  Ana Perez  "), _usuario()
        )
        self.assertTrue(ok, motivo)


class TestVectorDeSuplantacion(unittest.TestCase):
    """
    El ataque de C4: el atacante inserta un comando apuntando al usuario_id de
    un administrador para que el edge enrole SU cara en esa cuenta.
    """

    def setUp(self):
        self.admin = _usuario(nombre="Administrador", num_angulos=5, uid="u-admin")

    def test_disfrazado_de_alta_nueva_se_rechaza(self):
        """
        El atacante pone un nombre inocuo para que el operador que mira el HUD
        crea que se esta dando de alta a alguien nuevo.
        """
        ok, motivo, _ = validar_comando_registro(
            _comando(usuario_id="u-admin", nombre="Nuevo Empleado"), self.admin
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, NOMBRE_INCONSISTENTE)

    def test_con_el_nombre_real_tambien_se_rechaza(self):
        """
        Si usa el nombre real del administrador salva la comprobacion de
        consistencia, pero choca con el bloqueo de re-enrolamiento.
        """
        ok, motivo, ctx = validar_comando_registro(
            _comando(usuario_id="u-admin", nombre="Administrador"), self.admin
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, REENROLAMIENTO_NO_AUTORIZADO)
        self.assertTrue(ctx["es_reenrolamiento"])

    def test_el_atacante_no_puede_autoautorizarse_con_el_flag(self):
        """
        Sin firma, el flag del comando lo controla el atacante: no debe bastar.
        Solo vale la config LOCAL del dispositivo.
        """
        ok, motivo, _ = validar_comando_registro(
            _comando(usuario_id="u-admin", nombre="Administrador",
                     permitir_reenrolamiento=True),
            self.admin,
            permitir_reenrolamiento_local=False,
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, REENROLAMIENTO_NO_AUTORIZADO)

    def test_no_puede_crear_una_identidad_inexistente(self):
        """Apuntar a un usuario que no existe (o inactivo) no enrola nada."""
        ok, motivo, _ = validar_comando_registro(
            _comando(usuario_id="u-inventado"), None
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, USUARIO_NO_EXISTE)

    def test_comando_sin_usuario_id_se_rechaza(self):
        ok, motivo, _ = validar_comando_registro(
            _comando(usuario_id=None), _usuario()
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FALTA_USUARIO_ID)


class TestReenrolamientoLegitimo(unittest.TestCase):
    """Re-enrolar debe seguir siendo posible para quien tiene el dispositivo."""

    def setUp(self):
        self.usuario = _usuario(num_angulos=5)

    def test_config_local_autoriza(self):
        ok, motivo, _ = validar_comando_registro(
            _comando(), self.usuario, permitir_reenrolamiento_local=True
        )
        self.assertTrue(ok, motivo)

    def test_flag_firmado_autoriza(self):
        """Con firma, el flag va dentro de lo firmado: el atacante no lo toca."""
        cmd = _comando(permitir_reenrolamiento=True)
        cmd["firma"] = firma_esperada(
            SECRETO, cmd["tipo"], cmd["id"], cmd["usuario_id"], cmd["nombre"], True
        )
        ok, motivo, _ = validar_comando_registro(
            cmd, self.usuario, secreto_hmac=SECRETO
        )
        self.assertTrue(ok, motivo)


class TestFirmaHMAC(unittest.TestCase):

    def _firmado(self, **kwargs):
        cmd = _comando(**kwargs)
        cmd["firma"] = firma_esperada(
            SECRETO, cmd["tipo"], cmd["id"], cmd["usuario_id"], cmd.get("nombre"),
            bool(cmd.get("permitir_reenrolamiento")),
        )
        return cmd

    def test_comando_firmado_correctamente_pasa(self):
        ok, motivo, _ = validar_comando_registro(
            self._firmado(), _usuario(), secreto_hmac=SECRETO
        )
        self.assertTrue(ok, motivo)

    def test_sin_firma_se_rechaza_cuando_se_exige(self):
        ok, motivo, _ = validar_comando_registro(
            _comando(), _usuario(), secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FIRMA_INVALIDA)

    def test_firma_de_otro_secreto_se_rechaza(self):
        cmd = _comando()
        cmd["firma"] = firma_esperada(
            "otro-secreto", cmd["tipo"], cmd["id"], cmd["usuario_id"],
            cmd["nombre"], False
        )
        ok, motivo, _ = validar_comando_registro(
            cmd, _usuario(), secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FIRMA_INVALIDA)

    def test_manipular_el_usuario_id_invalida_la_firma(self):
        cmd = self._firmado()
        cmd["usuario_id"] = "u-admin"
        ok, motivo, _ = validar_comando_registro(
            cmd, _usuario(uid="u-admin"), secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FIRMA_INVALIDA)

    def test_activar_el_flag_a_posteriori_invalida_la_firma(self):
        """El flag esta dentro del mensaje firmado, no fuera."""
        cmd = self._firmado()
        cmd["permitir_reenrolamiento"] = True
        ok, motivo, _ = validar_comando_registro(
            cmd, _usuario(num_angulos=5), secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FIRMA_INVALIDA)

    def test_reusar_la_firma_en_otro_comando_falla(self):
        """
        El id del comando entra en el mensaje firmado, asi que una firma valida
        no se puede trasplantar a otra fila.
        """
        cmd = self._firmado()
        cmd["id"] = "cmd-2"
        ok, motivo, _ = validar_comando_registro(
            cmd, _usuario(), secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, FIRMA_INVALIDA)

    def test_la_firma_no_sustituye_a_las_demas_comprobaciones(self):
        """
        Un comando bien firmado que apunta a alguien inexistente sigue siendo
        invalido: la firma prueba el origen, no la coherencia.
        """
        ok, motivo, _ = validar_comando_registro(
            self._firmado(usuario_id="u-fantasma"), None, secreto_hmac=SECRETO
        )
        self.assertFalse(ok)
        self.assertEqual(motivo, USUARIO_NO_EXISTE)


class TestTieneBiometria(unittest.TestCase):

    def test_detecta_por_num_angulos(self):
        self.assertTrue(tiene_biometria({"num_angulos": 5}))
        self.assertFalse(tiene_biometria({"num_angulos": 0}))

    def test_detecta_por_embeddings(self):
        """num_angulos podria venir a 0 o nulo aunque haya plantillas."""
        self.assertTrue(tiene_biometria({"num_angulos": 0,
                                         "embeddings_json": [[0.0] * 128]}))

    def test_usuario_inexistente_no_tiene(self):
        self.assertFalse(tiene_biometria(None))
        self.assertFalse(tiene_biometria({}))


class TestContextoParaAuditoria(unittest.TestCase):

    def test_el_rechazo_deja_rastro_util(self):
        """
        Un rechazo sin contexto no sirve para investigar: hay que poder ver a
        quien apuntaba y con que nombre lo disfrazaron.
        """
        _, _, ctx = validar_comando_registro(
            _comando(usuario_id="u-admin", nombre="Nuevo Empleado"),
            _usuario(nombre="Administrador", num_angulos=5, uid="u-admin"),
        )
        self.assertEqual(ctx["usuario_id"], "u-admin")
        self.assertEqual(ctx["nombre_comando"], "Nuevo Empleado")
        self.assertEqual(ctx["nombre_db"], "Administrador")
        self.assertTrue(ctx["es_reenrolamiento"])


if __name__ == "__main__":
    unittest.main()
