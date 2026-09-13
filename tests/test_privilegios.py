"""
Guardarrail del inventario de privilegios.

Escanea el codigo buscando accesos a Supabase y comprueba que todos estan
declarados en backend/privilegios.py. Si alguien anade una operacion nueva,
este test falla y obliga a pasar por el inventario — y de ahi a revisar las
politicas RLS de supabase/rls_edge.sql.

Sin esto, la RLS se queda atras en silencio: el codigo pide mas permisos, la
service_role key se los concede sin rechistar, y nadie se entera hasta que
alguien audita.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.privilegios import (
    TABLAS, STORAGE, TABLAS_PROHIBIDAS,
    tablas_permitidas, buckets_permitidos, resumen,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS_ESCANEADOS = ("backend", "motor_ia", "config")

# .table("x") / .table('x')
RE_TABLA = re.compile(r"\.table\(\s*[\"']([^\"']+)[\"']")
# .from_("x")  (storage)
RE_BUCKET = re.compile(r"\.from_\(\s*[\"']([^\"']+)[\"']")


def _ficheros_python():
    for carpeta in DIRS_ESCANEADOS:
        base = os.path.join(RAIZ, carpeta)
        for dirpath, _, ficheros in os.walk(base):
            if "__pycache__" in dirpath:
                continue
            for f in ficheros:
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)


def _buscar(patron):
    """Retorna {valor: [rutas relativas donde aparece]}."""
    hallazgos = {}
    for ruta in _ficheros_python():
        with open(ruta, encoding="utf-8") as fh:
            contenido = fh.read()
        for valor in patron.findall(contenido):
            rel = os.path.relpath(ruta, RAIZ)
            hallazgos.setdefault(valor, []).append(rel)
    return hallazgos


class TestInventarioCompleto(unittest.TestCase):

    def test_toda_tabla_usada_esta_declarada(self):
        usadas = _buscar(RE_TABLA)
        declaradas = tablas_permitidas()

        no_declaradas = {t: v for t, v in usadas.items() if t not in declaradas}
        self.assertEqual(
            no_declaradas, {},
            "Tablas usadas en el codigo pero NO declaradas en "
            "backend/privilegios.py. Declaralas y actualiza "
            "supabase/rls_edge.sql:\n"
            + "\n".join(f"  {t}: {v}" for t, v in no_declaradas.items())
        )

    def test_toda_tabla_declarada_se_usa(self):
        """Un privilegio que ya no se usa debe retirarse, no acumularse."""
        usadas = set(_buscar(RE_TABLA))
        sin_usar = tablas_permitidas() - usadas
        self.assertEqual(
            sin_usar, set(),
            f"Declaradas en el inventario pero ya sin uso: {sin_usar}. "
            "Retiralas del inventario y revoca el GRANT."
        )

    def test_no_se_tocan_tablas_prohibidas(self):
        """
        El edge no debe acceder nunca a credenciales de admin ni a los
        endpoints de notificacion de los usuarios.
        """
        usadas = _buscar(RE_TABLA)
        violaciones = {t: v for t, v in usadas.items() if t in TABLAS_PROHIBIDAS}
        self.assertEqual(
            violaciones, {},
            "El edge accede a tablas prohibidas:\n"
            + "\n".join(f"  {t}: {v}" for t, v in violaciones.items())
        )

    def test_todo_bucket_usado_esta_declarado(self):
        usados = _buscar(RE_BUCKET)
        declarados = buckets_permitidos()
        no_declarados = {b: v for b, v in usados.items() if b not in declarados}
        self.assertEqual(
            no_declarados, {},
            "Buckets de Storage usados pero no declarados:\n"
            + "\n".join(f"  {b}: {v}" for b, v in no_declarados.items())
        )

    def test_el_escaner_encuentra_algo(self):
        """
        Si el regex dejara de casar, los tests de arriba pasarian vacios y el
        guardarrail seria inutil sin avisar.
        """
        self.assertGreater(len(_buscar(RE_TABLA)), 0, "el escaner no halla tablas")
        self.assertGreater(len(_buscar(RE_BUCKET)), 0, "el escaner no halla buckets")


class TestInventario(unittest.TestCase):

    def test_cada_privilegio_dice_donde_se_usa(self):
        """Un inventario sin trazabilidad no sirve para auditar."""
        for p in TABLAS + STORAGE:
            self.assertTrue(p.usado_en, f"{p.recurso} no dice donde se usa")
            self.assertTrue(p.nota, f"{p.recurso} no explica el alcance")

    def test_operaciones_son_conocidas(self):
        validas = {"select", "insert", "update", "delete", "upload", "remove"}
        for p in TABLAS + STORAGE:
            for op in p.operaciones:
                self.assertIn(op, validas, f"operacion desconocida: {op}")

    def test_resumen_es_legible(self):
        texto = resumen()
        self.assertIn("usuarios", texto)
        self.assertIn("capturas", texto)


if __name__ == "__main__":
    unittest.main()
