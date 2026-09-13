"""
Prueba de vida (liveness) 2D, sin sensor de profundidad.

POR QUE EXISTE ESTE MODULO
--------------------------
El verificador 3D solo es una prueba de vida cuando la profundidad viene de
un sensor real. Con la camara simulada la profundidad se generaba a partir
del bbox que habia encontrado el detector 2D, asi que el verificador validaba
una cupula que el propio sistema habia dibujado: cualquier rostro detectado
pasaba, foto impresa incluida, y siempre con las mismas metricas.

Este modulo aporta senales que SI dependen de lo que hay delante de la
camara, y que no necesitan hardware extra ni dependencias nuevas:

  1. PARPADEO (EAR). Una foto impresa no parpadea. Es la senal mas fuerte de
     las disponibles en 2D y la que decide.
  2. TEXTURA. Una pantalla introduce patron de moire (energia periodica de
     alta frecuencia) y reflejos especulares que la piel no tiene.

LIMITES (importantes, no son un detalle)
----------------------------------------
Esto NO es un PAD certificado. Concretamente:

  - El parpadeo derrota fotos impresas y capturas estaticas, pero NO un
     video en bucle de la persona: un video parpadea.
  - La textura ayuda contra pantallas, pero sus umbrales dependen de la
     camara, la optica y la iluminacion del sitio. Por eso por defecto se
     REGISTRA pero no BLOQUEA (ver LIVENESS_TEXTURA_BLOQUEA): un umbral sin
     calibrar en el sitio genera rechazos de personas legitimas.
  - Contra mascaras o video replay hace falta o un sensor de profundidad
     real, o un modelo de PAD pasivo (p.ej. MiniFASNet ONNX), o un reto
     activo aleatorio (girar la cabeza a un lado pedido al azar).

La defensa fuerte sigue siendo la camara 3D. Esto es el suelo, no el techo.
"""

import numpy as np

from config.settings import (
    LIVENESS_FACTOR_CIERRE, LIVENESS_FACTOR_APERTURA,
    LIVENESS_EAR_MINIMO, LIVENESS_FRAMES_BASE,
    LIVENESS_PARPADEO_MIN_FRAMES, LIVENESS_PARPADEO_MAX_FRAMES,
    LIVENESS_PARPADEOS_REQUERIDOS, LIVENESS_TIMEOUT,
    LIVENESS_TEXTURA_BLOQUEA, LIVENESS_MOIRE_MAX, LIVENESS_ESPECULAR_MAX,
)

# Estados posibles de la prueba de vida
PENDIENTE = "PENDIENTE"   # aun no hay evidencia suficiente (NO es fraude)
VIVO = "VIVO"             # prueba de vida superada
FALLO = "FALLO"           # evidencia activa de suplantacion

# Landmarks de los ojos en la malla de 468 puntos de MediaPipe.
# Orden EAR: (esquina_ext, sup_ext, sup_int, esquina_int, inf_int, inf_ext)
# Disponibles sin refine_landmarks (todos < 468).
OJO_IZQ = (33, 160, 158, 133, 153, 144)
OJO_DER = (362, 385, 387, 263, 373, 380)


def calcular_ear(puntos, indices):
    """
    Eye Aspect Ratio de un ojo.

    EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)

    Es la altura del ojo normalizada por su anchura, asi que no depende de
    la distancia a la camara. Ojo abierto ~0.25-0.35, cerrado < 0.15, pero
    el valor con ojo abierto varia mucho entre personas: de ahi el umbral
    adaptativo de DetectorParpadeo.

    Args:
        puntos: array (N, 2) de landmarks en pixeles.
        indices: tupla de 6 indices en el orden descrito arriba.

    Returns:
        float EAR, o 0.0 si la geometria es degenerada.
    """
    p1, p2, p3, p4, p5, p6 = (puntos[i] for i in indices)

    ancho = float(np.linalg.norm(p1 - p4))
    if ancho < 1e-6:
        return 0.0

    alto = float(np.linalg.norm(p2 - p6)) + float(np.linalg.norm(p3 - p5))
    return alto / (2.0 * ancho)


def calcular_ear_medio(puntos):
    """EAR promediado de ambos ojos. Retorna 0.0 si no hay landmarks."""
    if puntos is None or len(puntos) <= max(max(OJO_IZQ), max(OJO_DER)):
        return 0.0
    return (calcular_ear(puntos, OJO_IZQ) + calcular_ear(puntos, OJO_DER)) / 2.0


class DetectorParpadeo:
    """
    Maquina de estados de parpadeo con umbral adaptativo por persona.

    Un umbral fijo de EAR no sirve: alguien de ojos estrechos puede tener un
    EAR de 0.20 con los ojos bien abiertos y daria "parpadeando" siempre.
    Asi que primero se aprende la linea base de ESTA persona y el umbral se
    deriva de ella.

    Un parpadeo valido es un cierre que dura entre MIN y MAX frames y luego
    se reabre. El maximo importa: unos ojos cerrados de forma sostenida (una
    foto con los ojos cerrados, o alguien aguantando) no son un parpadeo.
    """

    def __init__(self):
        self._muestras_base = []
        self.linea_base = None
        self._cerrado = False
        self._frames_cerrado = 0
        self.parpadeos = 0
        self.ultimo_ear = 0.0

    @property
    def calibrado(self):
        return self.linea_base is not None

    def _umbrales(self):
        """(umbral_cierre, umbral_apertura) con histeresis."""
        return (self.linea_base * LIVENESS_FACTOR_CIERRE,
                self.linea_base * LIVENESS_FACTOR_APERTURA)

    def actualizar(self, ear):
        """
        Alimenta un EAR nuevo. Retorna True si acaba de completarse un
        parpadeo en este frame.
        """
        self.ultimo_ear = ear

        # --- Calibracion: aprender la linea base de esta persona ---
        if self.linea_base is None:
            # Solo muestras plausibles de ojo abierto; si la persona llega
            # parpadeando, esas muestras se descartan y se sigue esperando.
            if ear >= LIVENESS_EAR_MINIMO:
                self._muestras_base.append(ear)
            if len(self._muestras_base) < LIVENESS_FRAMES_BASE:
                return False
            # Mediana: robusta a los parpadeos que caigan en la ventana
            self.linea_base = float(np.median(self._muestras_base))
            return False

        umbral_cierre, umbral_apertura = self._umbrales()

        if not self._cerrado:
            if ear < umbral_cierre:
                self._cerrado = True
                self._frames_cerrado = 1
            return False

        # Estado cerrado
        if ear < umbral_apertura:
            self._frames_cerrado += 1
            return False

        # Reapertura: ¿fue un parpadeo o un cierre sostenido?
        duracion = self._frames_cerrado
        self._cerrado = False
        self._frames_cerrado = 0

        if LIVENESS_PARPADEO_MIN_FRAMES <= duracion <= LIVENESS_PARPADEO_MAX_FRAMES:
            self.parpadeos += 1
            return True
        return False


def analizar_textura(imagen_rgb, bbox):
    """
    Metricas de textura para distinguir piel de una pantalla.

    - moire: fraccion de energia del espectro que cae en alta frecuencia.
      Las pantallas, al ser una rejilla de pixeles fotografiada, anaden
      energia periodica ahi; la piel tiene un espectro mas suave.
    - especular: fraccion de pixeles casi saturados, o sea reflejos. Las
      pantallas y las fotos plastificadas reflejan de forma concentrada.

    Devuelve dict con las metricas (valores altos = mas sospechoso).
    Retorna {} si el recorte es demasiado pequeno para medir nada fiable.
    """
    alto_img, ancho_img = imagen_rgb.shape[:2]
    x, y, x2, y2 = bbox
    x = max(0, min(int(x), ancho_img)); x2 = max(0, min(int(x2), ancho_img))
    y = max(0, min(int(y), alto_img)); y2 = max(0, min(int(y2), alto_img))

    crop = imagen_rgb[y:y2, x:x2]
    if crop.size == 0 or crop.shape[0] < 32 or crop.shape[1] < 32:
        return {}

    gris = crop[:, :, 0] * 0.299 + crop[:, :, 1] * 0.587 + crop[:, :, 2] * 0.114

    # --- Moire: energia relativa en alta frecuencia ---
    # Ventana de Hann en 2D para que el borde del recorte no genere por si
    # solo energia de alta frecuencia (fuga espectral).
    ventana = np.outer(np.hanning(gris.shape[0]), np.hanning(gris.shape[1]))
    espectro = np.abs(np.fft.fftshift(np.fft.fft2(gris * ventana)))

    cy, cx = espectro.shape[0] // 2, espectro.shape[1] // 2
    yy, xx = np.ogrid[:espectro.shape[0], :espectro.shape[1]]
    radio = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    radio_max = min(cy, cx)

    if radio_max < 8:
        return {}

    total = float(espectro.sum())
    if total <= 0:
        return {}
    # Alta frecuencia: mas alla del 60% del radio disponible
    alta = float(espectro[radio > radio_max * 0.6].sum())
    moire = alta / total

    # --- Especular: pixeles casi saturados ---
    especular = float(np.mean(gris > 245))

    return {
        "moire": round(moire, 5),
        "especular": round(especular, 5),
    }


class VerificadorLiveness:
    """
    Combina las senales 2D en un veredicto por persona.

    El estado de parpadeo es por persona (vive en el PersonaTrack), asi que
    esta clase es sin estado: recibe el DetectorParpadeo del track.
    """

    def evaluar(self, detector, puntos, imagen_rgb, bbox, t_transcurrido):
        """
        Args:
            detector: DetectorParpadeo del track (estado temporal).
            puntos: landmarks del rostro en este frame.
            imagen_rgb: frame donde medir la textura.
            bbox: recorte del rostro.
            t_transcurrido: segundos desde que se vio a esta persona.

        Returns:
            (estado, motivo, metricas) con estado en {PENDIENTE, VIVO, FALLO}.
        """
        ear = calcular_ear_medio(puntos)
        detector.actualizar(ear)

        metricas = {
            "ear": round(ear, 4),
            "parpadeos": detector.parpadeos,
            "ear_base": round(detector.linea_base, 4) if detector.calibrado else None,
        }
        metricas.update(analizar_textura(imagen_rgb, bbox))

        # --- Textura: evidencia activa de pantalla ---
        # Por defecto NO bloquea: los umbrales dependen de la camara y la
        # iluminacion del sitio, y sin calibrar generan falsos rechazos.
        # Se registran para poder calibrarlos con datos reales.
        sospecha_textura = (
            metricas.get("moire", 0) > LIVENESS_MOIRE_MAX or
            metricas.get("especular", 0) > LIVENESS_ESPECULAR_MAX
        )
        if sospecha_textura and LIVENESS_TEXTURA_BLOQUEA:
            return FALLO, (
                f"Textura de pantalla (moire:{metricas.get('moire')} "
                f"espec:{metricas.get('especular')})"
            ), metricas

        # --- Parpadeo: la senal que decide ---
        if detector.parpadeos >= LIVENESS_PARPADEOS_REQUERIDOS:
            return VIVO, "Parpadeo verificado", metricas

        if t_transcurrido >= LIVENESS_TIMEOUT:
            # Tiempo de sobra delante de la camara y ni un parpadeo: eso ya
            # no es "aun no", es evidencia de que no hay una persona viva.
            return FALLO, f"Sin parpadeo en {LIVENESS_TIMEOUT:.0f}s", metricas

        return PENDIENTE, "Esperando parpadeo", metricas
