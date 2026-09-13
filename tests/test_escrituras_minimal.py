"""
Toda escritura a PostgREST debe pedir returning="minimal".

Este bug ha aparecido TRES veces con tres sintomas distintos:

  1. historial  -> "permission denied for table historial"
  2. usuarios   -> "permission denied for table usuarios"
  3. y estaba latente en estado_sistema y comandos_edge, que hoy funcionan solo
     porque el edge ve todas sus columnas: se romperian en cuanto alguien anada
     una columna que el edge no pueda leer.

La causa es siempre la misma y no es evidente leyendo el codigo: insert(),
update(), upsert() y delete() de postgrest-py llevan returning="representation"
POR DEFECTO, asi que despues de escribir hacen RETURNING * y eso exige permiso
de LECTURA sobre TODAS las columnas de la tabla. El edge tiene permisos de
columna deliberadamente estrechos —y sobre historial no tiene lectura ninguna,
para que un dispositivo robado no pueda leer el rastro de auditoria— asi que la
escritura fallaba aunque el INSERT o el UPDATE estuvieran concedidos.

En vez de arreglarlo una cuarta vez cuando aparezca, este test recorre el
codigo y exige que ninguna escritura se quede sin el parametro. Si alguna
escritura necesitara de verdad la fila de vuelta, hay que anadirla a
EXCEPCIONES y explicar por que.
"""

import os
import re
import unittest


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ficheros que hablan con PostgREST.
MODULOS = [
    "backend/supabase_sync.py",
    "backend/command_listener.py",
    "backend/heartbeat.py",
    "backend/cleanup.py",
    "backend/snapshot_uploader.py",
    "motor_ia/pipeline.py",
]

# Escrituras que SI necesitan la representacion de vuelta. Vacio a proposito:
# si alguna vez hace falta una, se anade aqui con su motivo, y asi la excepcion
# queda documentada en el sitio donde alguien la va a buscar.
EXCEPCIONES = {}

# Los metodos de escritura de postgrest-py. Todos tienen el mismo defecto.
ESCRITURAS = ("insert", "update", "upsert", "delete")

_LLAMADA = re.compile(
    r"\.(insert|update|upsert|delete)\s*\(", re.MULTILINE
)


def _cierre(texto, inicio):
    """Devuelve el indice del parentesis que cierra el abierto en `inicio`."""
    nivel = 0
    for i in range(inicio, len(texto)):
        if texto[i] in "([{":
            nivel += 1
        elif texto[i] in ")]}":
            nivel -= 1
            if nivel == 0:
                return i
    return len(texto) - 1


def escrituras_de_supabase(ruta):
    """
    Encuentra las llamadas de escritura a PostgREST de un fichero.

    Solo cuenta las que estan en una cadena que empieza por supabase.table(...)
    o .storage: `dict.update()` y `set.update()` de Python se llaman igual y no
    tienen nada que ver.

    Returns:
        Lista de (linea, metodo, tiene_minimal).
    """
    with open(os.path.join(RAIZ, ruta), encoding="utf-8") as f:
        texto = f.read()

    resultado = []
    for m in _LLAMADA.finditer(texto):
        metodo = m.group(1)
        # Mirar hacia atras en la misma sentencia para ver si esto cuelga de
        # una tabla de Supabase.
        inicio_sentencia = texto.rfind("\n", 0, max(0, m.start() - 400))
        contexto = texto[max(0, inicio_sentencia):m.start()]
        if "supabase.table(" not in contexto and ".table(" not in contexto:
            continue

        fin = _cierre(texto, m.end() - 1)
        argumentos = texto[m.start():fin + 1]
        linea = texto.count("\n", 0, m.start()) + 1
        resultado.append((linea, metodo, "returning" in argumentos))

    return resultado


class TestEscriturasMinimal(unittest.TestCase):

    def test_toda_escritura_declara_returning(self):
        fallos = []
        for ruta in MODULOS:
            for linea, metodo, tiene in escrituras_de_supabase(ruta):
                if tiene:
                    continue
                if EXCEPCIONES.get(f"{ruta}:{linea}"):
                    continue
                fallos.append(f"{ruta}:{linea} -> .{metodo}() sin returning")

        self.assertEqual(fallos, [], "\n".join([
            "",
            "Estas escrituras piden RETURNING * por defecto, y eso exige",
            "LECTURA de todas las columnas de la tabla. El rol del edge tiene",
            "permisos estrechos a proposito, asi que fallaran con",
            '"permission denied for table ..." aunque la escritura este',
            'concedida. Anade returning="minimal":',
            "",
        ] + fallos))

    def test_el_escaner_encuentra_algo(self):
        # Meta-test: si el escaner deja de reconocer las llamadas (porque
        # cambia el estilo del codigo), el test de arriba pasaria en verde sin
        # comprobar nada. Este lo impide.
        total = sum(len(escrituras_de_supabase(r)) for r in MODULOS)
        self.assertGreater(
            total, 5,
            "El escaner no encuentra escrituras de Supabase; probablemente "
            "dejo de reconocer el estilo del codigo y el test de arriba ya no "
            "comprueba nada."
        )

    def test_el_escaner_detecta_una_escritura_sin_returning(self):
        # Segundo meta-test: que de verdad distingue. Se comprueba sobre el
        # propio codigo, buscando una llamada conocida y verificando que el
        # escaner ve el parametro.
        escrituras = escrituras_de_supabase("backend/supabase_sync.py")
        self.assertTrue(escrituras, "no encontro las escrituras de historial")
        self.assertTrue(all(tiene for _, _, tiene in escrituras))

    def test_no_confunde_el_update_de_un_diccionario(self):
        # postura_seguridad.py hace cfg.update(kwargs) sobre un dict. Si el
        # escaner lo contara como escritura de Supabase, pediria un parametro
        # que ahi no existe.
        ruta = "backend/postura_seguridad.py"
        if os.path.exists(os.path.join(RAIZ, ruta)):
            self.assertEqual(escrituras_de_supabase(ruta), [])


if __name__ == "__main__":
    unittest.main()
