"""
Recarga periodica de la cache de plantillas.

Este fichero existe por un fallo que llego a produccion: el pipeline llamaba a
`reconocedor.huella_cache()`, un metodo que NO EXISTIA, y reventaba con
AttributeError. No lo cazo ningun test porque el camino solo se ejecuta cuando
pasan CACHE_REFRESH_INTERVAL segundos (60), y ninguna prueba corria tanto: el
sistema arrancaba bien, servia video, y se moria al minuto.

De ahi los dos tipos de test de aqui:
  * unitarios de la huella, incluida la independencia del ORDEN, que es lo que
    decide si el arreglo sirve o solo lo parece;
  * uno que EJECUTA la recarga de verdad, poniendo el intervalo a cero, porque
    un camino que ningun test recorre es un camino que nadie ha probado.
"""

import unittest

import numpy as np

from motor_ia.reconocimiento.embedding_generator import (
    ReconocedorFacial, _DIMENSIONES,
)


def _usuario(uid, nombre, semilla, n=2):
    rs = np.random.RandomState(semilla)
    return {
        "id": uid, "nombre": nombre,
        "embeddings": [rs.randn(_DIMENSIONES).tolist() for _ in range(n)],
    }


class TestHuellaCache(unittest.TestCase):

    def test_sin_plantillas(self):
        rec = ReconocedorFacial()
        self.assertEqual(rec.huella_cache(), "vacia")

    def test_las_mismas_plantillas_dan_la_misma_huella(self):
        us = [_usuario("a", "Ana", 1), _usuario("b", "Beto", 2)]
        r1 = ReconocedorFacial(); r1.cargar_cache(us)
        r2 = ReconocedorFacial(); r2.cargar_cache(us)
        self.assertEqual(r1.huella_cache(), r2.huella_cache())

    def test_es_estable_entre_llamadas(self):
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1)])
        self.assertEqual(rec.huella_cache(), rec.huella_cache())

    def test_NO_depende_del_orden_de_los_usuarios(self):
        # El test que decide si esto sirve. La consulta que carga usuarios no
        # lleva ORDER BY, asi que Postgres puede devolverlos en otro orden entre
        # dos recargas. Si la huella cambiara por eso, se reiniciaria el
        # reconocimiento cada minuto sin motivo: el sintoma que se venia a
        # eliminar, y encima pareceria arreglado.
        a, b = _usuario("a", "Ana", 1), _usuario("b", "Beto", 2)
        r1 = ReconocedorFacial(); r1.cargar_cache([a, b])
        r2 = ReconocedorFacial(); r2.cargar_cache([b, a])
        self.assertEqual(r1.huella_cache(), r2.huella_cache())

    def test_cambia_si_se_anade_un_usuario(self):
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1)])
        antes = rec.huella_cache()
        rec.cargar_cache([_usuario("a", "Ana", 1), _usuario("b", "Beto", 2)])
        self.assertNotEqual(rec.huella_cache(), antes)

    def test_cambia_si_se_quita_un_usuario(self):
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1), _usuario("b", "Beto", 2)])
        antes = rec.huella_cache()
        rec.cargar_cache([_usuario("a", "Ana", 1)])
        self.assertNotEqual(rec.huella_cache(), antes)

    def test_cambia_si_cambia_una_plantilla(self):
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1)])
        antes = rec.huella_cache()
        rec.cargar_cache([_usuario("a", "Ana", 99)])   # otros embeddings
        self.assertNotEqual(rec.huella_cache(), antes)

    def test_cambia_si_se_renombra_al_usuario(self):
        # El nombre se muestra en el preview y en el evento, asi que un cambio
        # de nombre tiene que propagarse.
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1)])
        antes = rec.huella_cache()
        rec.cargar_cache([_usuario("a", "Ana Maria", 1)])
        self.assertNotEqual(rec.huella_cache(), antes)

    def test_cambia_si_se_anade_una_pose_al_mismo_usuario(self):
        rec = ReconocedorFacial()
        rec.cargar_cache([_usuario("a", "Ana", 1, n=2)])
        antes = rec.huella_cache()
        rec.cargar_cache([_usuario("a", "Ana", 1, n=3)])
        self.assertNotEqual(rec.huella_cache(), antes)


class TestElPipelineEjecutaLaRecarga(unittest.TestCase):
    """
    Recorre de verdad el camino de la recarga periodica.

    Es el test que faltaba: con el intervalo a cero, la rama se ejecuta en cada
    frame, asi que un AttributeError ahi salta en segundos en vez de al minuto
    de estar en produccion.
    """

    def _correr(self, usuarios_por_recarga, frames=4):
        import queue
        import motor_ia.pipeline as pipeline
        from motor_ia.deteccion.face_mesh import DetectorFaceMesh
        from motor_ia.estado_registro import EstadoRegistro

        originales = {
            "crear_camara": pipeline.crear_camara,
            "cargar": pipeline._cargar_usuarios_supabase,
            "preview": pipeline.mostrar_preview,
            "snapshot": pipeline.subir_snapshot,
            "cliente": pipeline.obtener_cliente,
            "intervalo": pipeline.CACHE_REFRESH_INTERVAL,
            "detectar": DetectorFaceMesh.detectar,
        }

        class _Camara:
            profundidad_real = False
            def conectar(self): pass
            def obtener_frames(self):
                return np.zeros((480, 640, 3), dtype=np.uint8), None
            def cerrar(self): pass

        # Hace falta que HAYA un rostro. Descubierto al escribir este test: con
        # cero detecciones el bucle hace `continue` antes de llegar a la rama de
        # recarga, asi que la cache solo se refresca cuando hay alguien delante
        # de la camara. No es un problema —en cuanto aparece alguien y ya han
        # pasado los 60 s, se refresca en ese primer frame— pero explica por que
        # un test con la camara "vacia" no recorre este camino.
        from motor_ia.deteccion.face_mesh import RostroDetectado
        puntos = np.zeros((468, 2), dtype=np.float32)
        puntos[:] = (320.0, 240.0)
        rostro = RostroDetectado((280, 200, 360, 280), 0.0, 0.0, "frontal", puntos)

        cuenta = {"n": 0}
        def cargar():
            i = min(cuenta["n"], len(usuarios_por_recarga) - 1)
            cuenta["n"] += 1
            return usuarios_por_recarga[i]

        vistos = {"frames": 0}
        def preview(_):
            vistos["frames"] += 1
            return vistos["frames"] >= frames

        try:
            pipeline.crear_camara = lambda: _Camara()
            pipeline._cargar_usuarios_supabase = cargar
            pipeline.mostrar_preview = preview
            pipeline.subir_snapshot = lambda f: None
            pipeline.obtener_cliente = lambda: None
            pipeline.CACHE_REFRESH_INTERVAL = 0      # recargar cada frame
            DetectorFaceMesh.detectar = lambda self, img: [rostro]

            pipeline.ejecutar_pipeline(queue.Queue(), EstadoRegistro())
            return cuenta["n"]
        finally:
            pipeline.crear_camara = originales["crear_camara"]
            pipeline._cargar_usuarios_supabase = originales["cargar"]
            pipeline.mostrar_preview = originales["preview"]
            pipeline.subir_snapshot = originales["snapshot"]
            pipeline.obtener_cliente = originales["cliente"]
            pipeline.CACHE_REFRESH_INTERVAL = originales["intervalo"]
            DetectorFaceMesh.detectar = originales["detectar"]

    def test_la_recarga_no_revienta(self):
        # Habria cazado el AttributeError de huella_cache.
        recargas = self._correr([[_usuario("a", "Ana", 1)]])
        self.assertGreater(recargas, 1, "la rama de recarga no se ejecuto")

    def test_una_recarga_fallida_conserva_las_plantillas(self):
        # _cargar_usuarios_supabase devuelve None cuando no pudo cargar. Antes
        # devolvia [], indistinguible de "no hay usuarios", y la recarga
        # periodica borraba TODAS las plantillas por un corte de red de un
        # segundo: durante el minuto siguiente no se reconocia a nadie.
        buenos = [_usuario("a", "Ana", 1)]
        self._correr([buenos, None, None])

    def test_arrancar_sin_poder_cargar_no_revienta(self):
        self._correr([None])


class TestAtributosQueUsaElPipeline(unittest.TestCase):
    """
    Todo `objeto.atributo` que usa el pipeline tiene que existir.

    Complementa al test de integracion de arriba por otra via: aquel recorre un
    camino concreto, este revisa TODOS los accesos sin ejecutar nada. Es lo que
    cubre las ramas que solo se dan en situaciones raras —un fallo de red, un
    comando concreto, un temporizador largo— donde un metodo inexistente puede
    quedarse dormido meses y saltar en produccion.
    """

    def test_ningun_atributo_usado_falta(self):
        import re
        from motor_ia.estado_registro import EstadoRegistro
        from motor_ia.tracking import PersonaTrack

        with open("motor_ia/pipeline.py", encoding="utf-8") as f:
            fuente = f.read()

        objetos = {
            "reconocedor": ReconocedorFacial(),
            "track": PersonaTrack((0, 0, 10, 10), 0.0, "frontal"),
            "track_existente": PersonaTrack((0, 0, 10, 10), 0.0, "frontal"),
            "modo_registro": EstadoRegistro(),
        }

        faltan, revisados = [], 0
        for nombre, obj in objetos.items():
            usados = set(re.findall(
                rf"\b{nombre}\.([a-zA-Z_][a-zA-Z0-9_]*)", fuente))
            revisados += len(usados)
            faltan += [f"{nombre}.{a}" for a in sorted(usados)
                       if not hasattr(obj, a)]

        self.assertEqual(faltan, [], f"El pipeline usa atributos que no existen: {faltan}")
        # Meta-test: si el patron deja de encontrar accesos, el de arriba
        # pasaria en verde sin comprobar nada.
        self.assertGreater(revisados, 20)


if __name__ == "__main__":
    unittest.main()
