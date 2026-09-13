"""
La limpieza y los privilegios del edge.

Contexto del fallo real que motiva esto: el nodo en produccion imprimia cada
24 horas

    Error durante la limpieza: permission denied for table historial (42501)
    Traceback (most recent call last): ...

y acto seguido "Limpieza completada (nada que limpiar)". Las dos frases juntas
eran mentira: no es que no hubiera nada, es que no pudo ni mirar. El rol del
edge no tiene LECTURA sobre historial a proposito, asi que la consulta que
busca los registros caducados falla antes de llegar al borrado.

CLEANUP_EN_EDGE venia por defecto en true, contradiciendo el comentario que
tenia justo encima.
"""

import unittest

from backend import cleanup


class _APIErrorFalso(Exception):
    """Imita el APIError de postgrest, que serializa un dict en el mensaje."""

    def __init__(self, mensaje, codigo):
        super().__init__(
            "{'message': '%s', 'code': '%s', 'hint': None, 'details': None}"
            % (mensaje, codigo)
        )


class TestDeteccionDePrivilegios(unittest.TestCase):

    def test_reconoce_el_42501(self):
        error = _APIErrorFalso("permission denied for table historial", "42501")
        self.assertTrue(cleanup.es_falta_de_privilegios(error))

    def test_reconoce_el_texto_sin_codigo(self):
        self.assertTrue(
            cleanup.es_falta_de_privilegios(Exception("permission denied for schema storage"))
        )

    def test_no_confunde_otros_errores(self):
        # Un 504 del gateway o un fallo de red SI son reintentables: si los
        # tratara como falta de privilegios, apagaria la limpieza para siempre
        # por un corte de red pasajero.
        for otro in ("{'message': 'Gateway Timeout', 'code': 504}",
                     "Connection aborted",
                     "duplicate key value violates unique constraint"):
            self.assertFalse(
                cleanup.es_falta_de_privilegios(Exception(otro)), otro
            )


class _TablaFalsa:
    def __init__(self, al_leer=None, al_borrar=None, filas=None):
        self.al_leer = al_leer
        self.al_borrar = al_borrar
        self.filas = filas or []
        self._borrando = False

    def select(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def delete(self, **kwargs):
        # Acepta returning="minimal" como el cliente real: PostgREST devuelve
        # la fila borrada por defecto, y eso exige permiso de lectura.
        self._borrando = True
        return self

    def execute(self):
        if self._borrando:
            if self.al_borrar:
                raise self.al_borrar
            return type("R", (), {"data": []})()
        if self.al_leer:
            raise self.al_leer
        return type("R", (), {"data": self.filas})()


class _ClienteFalso:
    def __init__(self, tabla):
        self._tabla = tabla
        self.storage = type("S", (), {
            "from_": lambda s, b: type("B", (), {"remove": lambda s2, l: None})()
        })()

    def table(self, nombre):
        return self._tabla


class TestEjecutarLimpieza(unittest.TestCase):

    def _con_cliente(self, tabla):
        cleanup.obtener_cliente = lambda: _ClienteFalso(tabla)

    def tearDown(self):
        import importlib
        importlib.reload(cleanup)

    def test_sin_lectura_lanza_sin_privilegios(self):
        # Este es exactamente el fallo de produccion.
        self._con_cliente(_TablaFalsa(
            al_leer=_APIErrorFalso("permission denied for table historial", "42501")
        ))
        with self.assertRaises(cleanup.SinPrivilegios) as ctx:
            cleanup._ejecutar_limpieza()
        self.assertIn("lectura", str(ctx.exception))

    def test_sin_borrado_no_reporta_exito_vacio(self):
        # Si se concediera LECTURA pero no BORRADO, el bucle antiguo se tragaba
        # las 500 excepciones con `pass` y devolvia 0 eliminados, que se
        # imprimia como "nada que limpiar". Hay 500 filas que limpiar.
        self._con_cliente(_TablaFalsa(
            filas=[{"id": i, "foto_url": None} for i in range(3)],
            al_borrar=_APIErrorFalso("permission denied for table historial", "42501"),
        ))
        with self.assertRaises(cleanup.SinPrivilegios) as ctx:
            cleanup._ejecutar_limpieza()
        self.assertIn("borrado", str(ctx.exception))

    def test_un_error_reintentable_no_apaga_la_limpieza(self):
        self._con_cliente(_TablaFalsa(
            al_leer=Exception("{'message': 'Gateway Timeout', 'code': 504}")
        ))
        # No debe lanzar SinPrivilegios: devuelve 0,0 y se reintentara.
        self.assertEqual(cleanup._ejecutar_limpieza(), (0, 0))

    def test_sin_registros_antiguos_no_es_un_error(self):
        self._con_cliente(_TablaFalsa(filas=[]))
        self.assertEqual(cleanup._ejecutar_limpieza(), (0, 0))


class TestValorPorDefecto(unittest.TestCase):

    def test_cleanup_en_edge_es_false_por_defecto(self):
        # El defecto importa mas que el comentario: casi nadie declara esta
        # variable en su .env, asi que el valor por omision es el que corre en
        # produccion. En true producia un error cada 24 horas.
        import re
        with open("config/settings.py", encoding="utf-8") as f:
            fuente = f.read()
        m = re.search(r'CLEANUP_EN_EDGE = _env\.get\("CLEANUP_EN_EDGE", "(\w+)"\)', fuente)
        self.assertIsNotNone(m, "no encuentro la definicion de CLEANUP_EN_EDGE")
        self.assertEqual(
            m.group(1), "false",
            "Con la clave restringida el edge no puede limpiar: no tiene "
            "lectura sobre historial."
        )

    def test_el_env_example_tampoco_lo_activa(self):
        with open(".env.example", encoding="utf-8") as f:
            lineas = [l.strip() for l in f if l.strip().startswith("CLEANUP_EN_EDGE=")]
        self.assertEqual(lineas, ["CLEANUP_EN_EDGE=false"])


if __name__ == "__main__":
    unittest.main()
