"""
Seguimiento de personas entre frames.

Vive separado del pipeline porque es logica pura (sin camara, sin modelos,
sin Supabase): asi se puede testear sin levantar todo el stack.
"""

import time
from collections import Counter, deque

from config.settings import VOTOS_VENTANA, VOTOS_REQUERIDOS
from motor_ia.antispoofing.liveness import DetectorParpadeo, PENDIENTE


# Timeout para considerar que una persona se fue (segundos)
_SESION_TIMEOUT = 30

# IoU minimo para considerar que una deteccion es el mismo track
UMBRAL_IOU_TRACKING = 0.25

# Distancia maxima entre centroides en la pasada de respaldo (pixeles)
UMBRAL_PX_TRACKING = 120


# ======================================================================
# PersonaTrack: estado independiente por cada persona detectada
# ======================================================================

class PersonaTrack:
    """Estado de seguimiento para una persona individual en el frame."""

    def __init__(self, bbox, angulo, direccion, angulo_v=0.0):
        # Posición actual
        self.bbox = bbox
        self.angulo = angulo
        self.angulo_v = angulo_v
        self.direccion = direccion

        # Anti-spoofing 3D
        self.spoofing_cache = None   # (es_real, es_dist, motivo, metricas)
        self.t_spoofing = 0

        # Prueba de vida (liveness 2D). El parpadeo es una senal temporal,
        # asi que su estado vive con la persona, no con el frame.
        self.parpadeo = DetectorParpadeo()
        self.liveness_estado = PENDIENTE
        self.liveness_motivo = "Esperando parpadeo"
        self.liveness_metricas = {}
        self.primera_vez_visto = time.time()

        # Reconocimiento
        self.nombre = None
        self.confianza = 0
        self.usuario_id = None
        # Instante a partir del cual se permite el proximo embedding
        self.t_proximo_embedding = 0
        # Motivo por el que se saltó el ultimo reconocimiento (pose/calidad)
        self.motivo_gate = ""
        # Por que NO se reconocio al ultimo embedding, con la distancia. Un
        # "persona no registrada" sin numero no se puede diagnosticar.
        self.motivo_no_reconocido = ""
        self.distancia_mejor = None

        # Votación temporal: ventana de las ultimas identificaciones.
        # Un unico embedding no decide la identidad; hacen falta
        # VOTOS_REQUERIDOS coincidencias dentro de la ventana.
        self._votos = deque(maxlen=VOTOS_VENTANA)

        # Sesión (evitar eventos repetidos)
        self.sesion_tipo = None      # "ACCESO_PERMITIDO", "DESCONOCIDO", "FRAUDE"
        self.sesion_sujeto = None

        # Tracking
        self.ultimo_visto = time.time()
        self.id = id(self)  # Identificador único del track

    def centroide(self):
        """Retorna (cx, cy) del centro del bbox."""
        x, y, x2, y2 = self.bbox
        return ((x + x2) / 2, (y + y2) / 2)

    def actualizar_posicion(self, bbox, angulo, direccion, angulo_v=0.0):
        """Actualiza la posición del track con la nueva detección."""
        self.bbox = bbox
        self.angulo = angulo
        self.angulo_v = angulo_v
        self.direccion = direccion
        self.ultimo_visto = time.time()

    # --- Votación temporal -------------------------------------------

    def registrar_voto(self, usuario_id, nombre, confianza=0.0):
        """
        Acumula una identificación en la ventana de votos.
        usuario_id None representa "desconocido", que también vota.
        """
        self._votos.append((usuario_id, nombre, confianza))

    def limpiar_votos(self):
        """Descarta la ventana (p.ej. al recargar la caché de usuarios)."""
        self._votos.clear()

    def veredicto(self):
        """
        Resuelve la ventana de votos.

        Retorna (hay_veredicto, usuario_id, nombre, confianza).
        hay_veredicto es False mientras ninguna opción alcance
        VOTOS_REQUERIDOS: es lo que evita que una única inferencia
        errónea dispare un evento de acceso.
        """
        if not self._votos:
            return False, None, None, 0.0

        clave, n = Counter(v[0] for v in self._votos).most_common(1)[0]
        if n < VOTOS_REQUERIDOS:
            return False, None, None, 0.0

        # De los votos ganadores, quedarse con el más confiado
        mejor = max((v for v in self._votos if v[0] == clave), key=lambda v: v[2])
        return True, mejor[0], mejor[1], mejor[2]

    def tiempo_visible(self, ahora):
        """Segundos desde que se vio a esta persona por primera vez."""
        return ahora - self.primera_vez_visto

    def esta_activo(self, ahora):
        """Retorna True si el track sigue activo (no ha expirado)."""
        return (ahora - self.ultimo_visto) < _SESION_TIMEOUT

    def to_vis_dict(self):
        """Convierte el track a dict para visualización."""
        es_real = True
        es_dist = False
        motivo = ""
        metricas = {}

        if self.spoofing_cache:
            es_real, es_dist, motivo, metricas = self.spoofing_cache

        return {
            "bbox": self.bbox,
            "es_real": es_real,
            "es_dist": es_dist,
            "motivo": motivo,
            "metricas": metricas,
            "nombre": self.nombre,
            "confianza": self.confianza,
            "motivo_gate": self.motivo_gate,
            "motivo_no_reconocido": self.motivo_no_reconocido,
            "distancia_mejor": self.distancia_mejor,
            "liveness_estado": self.liveness_estado,
            "liveness_motivo": self.liveness_motivo,
        }


def distancia_centroides(bbox_a, bbox_b):
    """Distancia euclidiana entre los centroides de dos bboxes."""
    cx_a = (bbox_a[0] + bbox_a[2]) / 2
    cy_a = (bbox_a[1] + bbox_a[3]) / 2
    cx_b = (bbox_b[0] + bbox_b[2]) / 2
    cy_b = (bbox_b[1] + bbox_b[3]) / 2
    return ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5


def iou(bbox_a, bbox_b):
    """Intersection over Union de dos bboxes (x, y, x2, y2)."""
    ax, ay, ax2, ay2 = bbox_a
    bx, by, bx2, by2 = bbox_b

    solape_x = min(ax2, bx2) - max(ax, bx)
    solape_y = min(ay2, by2) - max(ay, by)
    if solape_x <= 0 or solape_y <= 0:
        return 0.0

    interseccion = solape_x * solape_y
    area_a = max(0, ax2 - ax) * max(0, ay2 - ay)
    area_b = max(0, bx2 - bx) * max(0, by2 - by)
    union = area_a + area_b - interseccion

    if union <= 0:
        return 0.0
    return interseccion / union


def asociar_detecciones(tracks, detecciones,
                         umbral_iou=UMBRAL_IOU_TRACKING,
                         umbral_px=UMBRAL_PX_TRACKING):
    """
    Asocia detecciones nuevas con tracks existentes.

    Retorna lista de (track_o_None, rostro) en el mismo orden que
    `detecciones`. track=None significa detección nueva (persona que
    acaba de aparecer).

    Antes esto era greedy por centroide en el orden de llegada de las
    detecciones: la primera detección se quedaba con el track más cercano
    aunque otra detección le encajara mucho mejor, lo que intercambiaba
    identidades (y con ellas la sesión ya reconocida) entre dos personas
    que se cruzaban. Ahora se evalúan TODOS los pares y se asignan los
    mejores primero, puntuando por IoU — que tiene en cuenta tamaño y
    solape, no solo la distancia entre centros.
    """
    resultado = [None] * len(detecciones)

    if not tracks:
        return [(None, det) for det in detecciones]

    libres_track = set(range(len(tracks)))
    libres_det = set(range(len(detecciones)))

    def _asignar(pares, invertir):
        """Asignación global greedy: los mejores pares primero."""
        pares.sort(reverse=invertir)
        for _, i, j in pares:
            if i in libres_track and j in libres_det:
                libres_track.discard(i)
                libres_det.discard(j)
                resultado[j] = (tracks[i], detecciones[j])

    # Pasada 1: IoU (mayor es mejor)
    pares_iou = []
    for i in libres_track:
        for j in libres_det:
            valor_iou = iou(tracks[i].bbox, detecciones[j].bbox)
            if valor_iou >= umbral_iou:
                pares_iou.append((valor_iou, i, j))
    _asignar(pares_iou, invertir=True)

    # Pasada 2: centroide (menor es mejor) para movimiento rápido, donde
    # los bboxes de dos frames consecutivos ya no se solapan.
    pares_dist = []
    for i in libres_track:
        for j in libres_det:
            dist = distancia_centroides(tracks[i].bbox, detecciones[j].bbox)
            if dist < umbral_px:
                pares_dist.append((dist, i, j))
    _asignar(pares_dist, invertir=False)

    # Lo que quede sin asignar son personas nuevas
    for j in libres_det:
        resultado[j] = (None, detecciones[j])

    return resultado


def escalar_bbox(bbox, escala, ancho_max, alto_max):
    """
    Reproyecta un bbox detectado en el frame reducido sobre el frame de
    resolución nativa.

    La detección corre a ANCHO_DETECCION porque es barata ahí, pero el
    embedding no tiene por qué conformarse con esos píxeles: un rostro
    lejano que en el frame reducido ocupa 70x70 px puede ocupar 140x140
    en el frame original, y esos píxeles ya están capturados.
    """
    x, y, x2, y2 = bbox
    return (
        max(0, int(x * escala)),
        max(0, int(y * escala)),
        min(ancho_max, int(x2 * escala)),
        min(alto_max, int(y2 * escala)),
    )


def persona_mas_grande(tracks):
    """Retorna el track con el bbox más grande (persona más cercana)."""
    if not tracks:
        return None
    return max(tracks, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))


def prioridad_reconocimiento(par):
    """
    Clave de orden para repartir el presupuesto de embeddings del frame.

    Primero quien todavía no tiene veredicto (hay que identificarlo) y,
    entre ellos, el más cercano a la cámara. Sin esto, un track ya resuelto
    podría quedarse el único turno del frame y retrasar la identificación de
    alguien que acaba de entrar.

    `par` es una tupla (track_o_None, rostro) de asociar_detecciones.
    """
    track, rostro = par
    sin_veredicto = (
        track is None or
        track.sesion_tipo not in ("ACCESO_PERMITIDO", "DESCONOCIDO")
    )
    x, y, x2, y2 = rostro.bbox
    area = (x2 - x) * (y2 - y)
    return (0 if sin_veredicto else 1, -area)
