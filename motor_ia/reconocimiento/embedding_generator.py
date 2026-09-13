"""
Genera y compara embeddings faciales.

El matching hace tres cosas que un vecino-mas-cercano simple no hace:

  1. Agrega por IDENTIDAD, no por plantilla. Cada usuario tiene varias
     plantillas (una por angulo); su puntuacion es la mejor de las suyas.

  2. Exige un MARGEN entre la mejor identidad y la segunda mejor identidad
     distinta. Con un umbral absoluto suelto, la probabilidad de que
     *alguien* de la base caiga por debajo del umbral por azar crece con el
     numero de usuarios. El margen convierte los empates en rechazos.

  3. Devuelve una confianza CALIBRADA (sigmoide centrada en el umbral) en
     vez de `1 - distancia`, que no es una probabilidad: un match correcto
     a distancia 0.42 se mostraba como 58% y parecia dudoso.
"""

import math
from collections import namedtuple

import cv2
import numpy as np
import face_recognition

from config.settings import (
    TOLERANCIA_FACIAL, MARGEN_IDENTIDAD, ESCALA_CONFIANZA,
    PENALIZACION_POSE, JITTERS_RECONOCIMIENTO,
    MOTOR_EMBEDDING, RUTA_MODELO_ONNX, ONNX_HILOS,
    TOLERANCIA_FACIAL_ONNX, MARGEN_IDENTIDAD_ONNX, ESCALA_CONFIANZA_ONNX,
)
from motor_ia.estado_registro import ANGULOS_REGISTRO


# Los dos motores miden la MISMA distancia euclidea, pero sobre espacios
# distintos: dlib da vectores de 128 dimensiones sin normalizar, y el motor ONNX
# da 512 normalizados a norma 1. Los umbrales no son intercambiables, asi que se
# resuelven una vez aqui segun el motor activo en vez de repartir condicionales
# por el codigo de matching.
_USA_ONNX = MOTOR_EMBEDDING == "onnx"

if _USA_ONNX:
    _TOLERANCIA = TOLERANCIA_FACIAL_ONNX
    _MARGEN = MARGEN_IDENTIDAD_ONNX
    _ESCALA = ESCALA_CONFIANZA_ONNX
    _DIMENSIONES = 512
else:
    _TOLERANCIA = TOLERANCIA_FACIAL
    _MARGEN = MARGEN_IDENTIDAD
    _ESCALA = ESCALA_CONFIANZA
    _DIMENSIONES = 128


# Resultado de consultar un embedding contra la cache. Lleva la distancia y el
# margen para que un rechazo se pueda diagnosticar en vez de adivinar.
Coincidencia = namedtuple(
    "Coincidencia",
    ["nombre", "confianza", "usuario_id", "distancia", "margen", "motivo"]
)


def calibrar_confianza(distancia, umbral=None, escala=None):
    """
    Convierte una distancia euclidiana en una confianza 0..1 monotona
    decreciente, con 0.50 exactamente en el umbral de aceptacion.

    Sustituye a `1 - distancia`, que no estaba en ninguna escala util.
    """
    umbral = _TOLERANCIA if umbral is None else umbral
    escala = _ESCALA if escala is None else escala

    # Acotar el exponente para que no desborde con distancias grandes
    exponente = max(-60.0, min(60.0, (float(distancia) - umbral) / escala))
    return round(1.0 / (1.0 + math.exp(exponente)), 4)


class ReconocedorFacial:

    def __init__(self):
        # Lista de dicts (id/nombre/embedding/angulo). Se mantiene por
        # compatibilidad e introspeccion; el matching usa las matrices.
        self.cache = []

        # Representacion vectorizada de la cache
        self._matriz = np.zeros((0, _DIMENSIONES), dtype=np.float64)  # (M, D)
        self._angulos = np.zeros(0, dtype=object)             # (M,) angulo por plantilla
        self._idx_identidad = np.zeros(0, dtype=np.int64)     # (M,) -> indice de identidad
        self._identidades = []                               # [(usuario_id, nombre), ...]

        # CLAHE: ecualización adaptativa de histograma
        # Normaliza iluminación desigual (sombras, contraluz, etc.)
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # Motor ONNX: se crea al primer uso y no en el constructor, para que
        # importar este modulo no exija tener el modelo descargado ni
        # onnxruntime instalado cuando el motor activo es dlib.
        self._motor_onnx = None

    def _onnx(self):
        if self._motor_onnx is None:
            from motor_ia.reconocimiento.motor_onnx import MotorONNX
            self._motor_onnx = MotorONNX(RUTA_MODELO_ONNX, hilos=ONNX_HILOS)
            print(f"    Motor de embeddings: ONNX ({_DIMENSIONES}D) "
                  f"desde {RUTA_MODELO_ONNX}")
        return self._motor_onnx

    # ------------------------------------------------------------------
    # Generacion de embeddings
    # ------------------------------------------------------------------

    def _preprocesar_rostro(self, imagen_rgb, bbox):
        """
        Normaliza la iluminación del recorte facial usando CLAHE
        sobre el canal de luminosidad (LAB), preservando los colores.
        Retorna imagen completa con el rostro mejorado.
        """
        x, y, x2, y2 = bbox

        # Validar que el crop tiene tamaño mínimo viable
        if x2 - x < 20 or y2 - y < 20:
            return imagen_rgb

        imagen_out = imagen_rgb.copy()

        # Convertir crop a LAB (separar luminosidad del color)
        crop_rgb = imagen_out[y:y2, x:x2]
        crop_lab = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2LAB)

        # Aplicar CLAHE solo al canal L (luminosidad)
        crop_lab[:, :, 0] = self._clahe.apply(crop_lab[:, :, 0])

        # Convertir de vuelta a RGB y reemplazar en la imagen
        imagen_out[y:y2, x:x2] = cv2.cvtColor(crop_lab, cv2.COLOR_LAB2RGB)

        return imagen_out

    def generar_embedding(self, imagen_rgb, bbox, num_jitters=None, puntos=None):
        """
        Genera el vector del rostro con el motor configurado.

        Con MOTOR_EMBEDDING=onnx son 512 dimensiones normalizadas a norma 1;
        con dlib, 128 sin normalizar. No son comparables entre si.

        Args:
            imagen_rgb: frame del que recortar.
            bbox: (x, y, x2, y2) en coordenadas de ESE frame.
            num_jitters: solo dlib. Numero de transformaciones que promedia:
                1 en reconocimiento (coste), mas en registro (la plantilla de
                referencia se calcula una sola vez, asi que ahi importa mas la
                calidad que el tiempo).
            puntos: landmarks (N, 2) en coordenadas de ese mismo frame. El
                motor ONNX los usa para alinear el rostro por 5 puntos, que es
                como se entreno; sin ellos cae en un simple reescalado del
                recorte, que es peor. dlib los ignora: alinea por su cuenta.
        """
        if _USA_ONNX:
            return self._onnx().generar(imagen_rgb, bbox, puntos)

        if num_jitters is None:
            num_jitters = JITTERS_RECONOCIMIENTO

        x, y, x2, y2 = bbox

        # Preprocesar: normalizar iluminación del rostro
        imagen_mejorada = self._preprocesar_rostro(imagen_rgb, bbox)

        ubicacion = [(y, x2, y2, x)]

        encodings = face_recognition.face_encodings(
            imagen_mejorada, ubicacion, num_jitters=num_jitters, model="large"
        )

        if encodings:
            return encodings[0]
        return None

    def generar_lote(self, imagen_rgb, rostros):
        """
        Embeddings de VARIOS rostros del mismo frame.

        Con ONNX es una sola inferencia y ahi esta la ganancia del caso
        multi-rostro: medido, 5 rostros en 26 ms (5.2 ms cada uno) frente a
        7.6 ms cuando va de uno en uno. Con dlib no hay lote posible, asi que
        se recorre; se ofrece igual para que quien llame no tenga que
        preguntar por el motor.

        Args:
            rostros: lista de (bbox, puntos).

        Returns:
            Lista de vectores (o None en las posiciones que fallaron).
        """
        if not rostros:
            return []

        if _USA_ONNX:
            matriz = self._onnx().generar_lote(imagen_rgb, rostros)
            return [fila for fila in matriz]

        return [self.generar_embedding(imagen_rgb, bbox, puntos=puntos)
                for bbox, puntos in rostros]

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def buscar(self, embedding, pose=None):
        """
        Busca la identidad del embedding en la cache.

        Envoltorio de `evaluar` que devuelve solo lo imprescindible, para los
        sitios a los que el detalle del rechazo no les aporta nada.

        Returns:
            (nombre, confianza, usuario_id) — (None, 0.0, None) si se rechaza.
        """
        r = self.evaluar(embedding, pose)
        return r.nombre, r.confianza, r.usuario_id

    def evaluar(self, embedding, pose=None):
        """
        Como `buscar`, pero explicando POR QUE.

        Existe porque un rechazo sin numero es imposible de diagnosticar: el
        sistema dice "persona no registrada" y no hay forma de saber si se
        quedo a un pelo del umbral o lejisimos. Con la distancia a la mano, la
        diferencia entre "hay que ajustar el umbral" y "esa persona no esta
        registrada" se ve de un vistazo.

        Args:
            embedding: vector consultado.
            pose: direccion detectada ("frontal", "izquierda", ...) o None.
                Si se indica, las plantillas registradas en otro angulo
                reciben una penalizacion pequena.

        Returns:
            Coincidencia(nombre, confianza, usuario_id, distancia, margen,
            motivo). `distancia` es a la identidad mas cercana y `margen` la
            separacion con la segunda; ambos None si la cache esta vacia.
        """
        if self._matriz.shape[0] == 0:
            return Coincidencia(None, 0.0, None, None, None, "sin plantillas")

        emb = np.asarray(embedding, dtype=np.float64)

        # Distancias a todas las plantillas de una vez.
        # El bucle Python anterior recorria cada entrada de la cache; con
        # cientos de usuarios eso se ejecutaba cada COOLDOWN_EMBEDDING y por
        # persona en el frame.
        distancias = np.linalg.norm(self._matriz - emb, axis=1)

        # Pista suave de pose: penaliza comparar un rostro frontal contra
        # la plantilla de "arriba", que puede dar un falso minimo.
        if pose and PENALIZACION_POSE > 0:
            distintas = self._angulos != pose
            distancias = distancias + PENALIZACION_POSE * distintas

        # Mejor plantilla de cada identidad
        n_identidades = len(self._identidades)
        por_identidad = np.full(n_identidades, np.inf)
        np.minimum.at(por_identidad, self._idx_identidad, distancias)

        orden = np.argsort(por_identidad)
        mejor = int(orden[0])
        d1 = float(por_identidad[mejor])

        # Distancia de la mejor identidad DISTINTA (inf si solo hay una)
        d2 = float(por_identidad[orden[1]]) if n_identidades > 1 else float("inf")

        margen = None if d2 == float("inf") else d2 - d1

        if d1 >= _TOLERANCIA:
            return Coincidencia(
                None, 0.0, None, d1, margen,
                f"lejos: {d1:.3f} >= umbral {_TOLERANCIA:.3f}"
            )

        # Test de margen: si otra persona esta casi igual de cerca, es un
        # empate y no una identificacion.
        if margen is not None and margen < _MARGEN:
            return Coincidencia(
                None, 0.0, None, d1, margen,
                f"empate: segunda a {margen:.3f}, margen minimo {_MARGEN:.3f}"
            )

        usuario_id, nombre = self._identidades[mejor]
        return Coincidencia(
            nombre, calibrar_confianza(d1), usuario_id, d1, margen, ""
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def cargar_cache(self, usuarios):
        """
        Carga embeddings de usuarios a memoria (lista + matrices).

        El angulo de cada plantilla se toma de `usuario["angulos"]` si viene,
        y si no del orden de captura: el registro recorre ANGULOS_REGISTRO en
        secuencia, asi que embeddings[i] corresponde a ANGULOS_REGISTRO[i].
        """
        self.cache = []
        self._identidades = []

        filas = []
        angulos = []
        idx_identidad = []
        incompatibles = []

        for usuario in usuarios:
            if "embeddings" in usuario:
                lista = usuario["embeddings"]
            elif "embedding" in usuario:
                lista = [usuario["embedding"]]
            else:
                continue

            if not lista:
                continue

            etiquetas = usuario.get("angulos") or []
            idx = len(self._identidades)
            self._identidades.append((usuario.get("id"), usuario["nombre"]))

            for i, emb in enumerate(lista):
                if i < len(etiquetas):
                    angulo = etiquetas[i]
                elif i < len(ANGULOS_REGISTRO):
                    angulo = ANGULOS_REGISTRO[i]
                else:
                    angulo = None

                vector = np.asarray(emb, dtype=np.float64)

                # Plantilla de OTRO motor: se descarta.
                #
                # Los dos motores producen espacios distintos e incomparables
                # (128D sin normalizar contra 512D normalizado). Si se cambia
                # MOTOR_EMBEDDING sin volver a registrar, aqui llegan vectores
                # de la longitud equivocada. Compararlos no es que diera peor
                # precision: `self._matriz - emb` con longitudes distintas o
                # revienta o hace broadcast y devuelve numeros sin significado,
                # y el sistema acabaria concediendo o denegando accesos por
                # aritmetica basura. Mejor no reconocer a nadie y decirlo.
                if vector.shape[-1] != _DIMENSIONES:
                    incompatibles.append(
                        (usuario.get("nombre", "?"), int(vector.shape[-1]))
                    )
                    continue

                filas.append(vector)
                angulos.append(angulo)
                idx_identidad.append(idx)

                self.cache.append({
                    "id": usuario.get("id"),
                    "nombre": usuario["nombre"],
                    "embedding": vector,
                    "angulo": angulo,
                })

        if filas:
            self._matriz = np.vstack(filas)
            self._angulos = np.array(angulos, dtype=object)
            self._idx_identidad = np.array(idx_identidad, dtype=np.int64)
        else:
            self._matriz = np.zeros((0, _DIMENSIONES), dtype=np.float64)
            self._angulos = np.zeros(0, dtype=object)
            self._idx_identidad = np.zeros(0, dtype=np.int64)

        print(f"    Caché: {len(self.cache)} embeddings / {len(self._identidades)} usuarios")

        if incompatibles:
            nombres = sorted({n for n, _ in incompatibles})
            dims = sorted({d for _, d in incompatibles})
            print(f"     {len(incompatibles)} plantillas DESCARTADAS por ser de "
                  f"otro motor: {dims} dimensiones, se esperaban {_DIMENSIONES}.")
            print(f"       Afecta a: {', '.join(nombres)}")
            print(f"       MOTOR_EMBEDDING={MOTOR_EMBEDDING} exige volver a "
                  f"registrar a esos usuarios.")
            if not self.cache:
                print("       NO SE RECONOCERA A NADIE hasta que se registren "
                      "de nuevo.")

    def recargar_cache(self, usuarios):
        """Alias para actualizar después de registrar."""
        self.cargar_cache(usuarios)
