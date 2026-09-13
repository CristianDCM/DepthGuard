"""
Camara simulada: webcam normal, SIN profundidad.

Antes esta clase fabricaba un mapa de profundidad a partir del bbox que ya
habia detectado el pipeline (`actualizar_profundidad`). Eso convertia el
anti-spoofing 3D en una tautologia: el verificador validaba una cupula que el
propio sistema acababa de dibujar, asi que cualquier rostro detectado pasaba
como "real" —foto impresa incluida— y siempre con las mismas metricas
(distancia 68.8 cm, varianza 1.57, rango 4.1 en cualquier situacion).

Ahora devuelve profundidad None y lo declara con `profundidad_real = False`.
El pipeline no ejecuta el verificador 3D sin datos reales; la prueba de vida
en este modo la aporta motor_ia/antispoofing/liveness.py (parpadeo).

--- Resolucion nativa ---

La webcam se abre a CAMARA_ANCHO x CAMARA_ALTO (1280x960 por defecto), no a
640x480. Esto NO sube el coste de detectar ni el ancho de banda: el pipeline
reduce el frame a 640 antes de detectar, de dibujar el preview y de enviarlo
por WebRTC. La resolucion nativa la consume un unico sitio, el recorte del
que sale el embedding, y ahi se nota: a 640x480 una cara a metro y medio son
~90x120 px que dlib interpola hasta su chip de 150x150; a 1280x960 son
~180x240 px reales. El embedding cuesta lo mismo en ambos casos (medido:
108 ms con un recorte de 90x120 y 109 ms con uno de 180x240, porque dlib
reescala internamente), asi que la precision extra sale gratis.

Lo unico que se paga es decodificar un JPEG mas grande: ~5.8 ms por frame
frente a ~1.2 ms. Por eso el formato importa tanto —ver abajo.
"""

import time

import cv2

from config.settings import CAMARA_ANCHO, CAMARA_ALTO, CAMARA_FPS


# Se pide MJPG, pero NO porque sea mejor: porque es el unico formato que
# cabe por un bus estrecho.
#
# Una webcam UVC ofrece dos familias de formato. Sin comprimir (YUY2/YUYV,
# 2 bytes por pixel) 1280x960 son 2,4 MB por frame: a 30 FPS son ~74 MB/s,
# mas de lo que da un USB 2.0 (~35 MB/s reales). El driver no falla ni
# avisa, simplemente negocia menos FPS hasta que cabe. MJPG va comprimido
# en la propia camara (~0,9 MB por frame, ~28 MB/s), asi que entra.
#
# Pero si el bus da de si —una camara interna de portatil, o USB 3.0— el
# formato sin comprimir es PREFERIBLE, y por un margen grande. Medido a
# 1280x960: convertir YUY2 a BGR cuesta 0,21 ms, mientras que decodificar
# el JPEG de MJPG cuesta entre 5 y 14 ms. Comprimir en la camara para
# descomprimir en la CPU solo tiene sentido cuando el cable es el cuello
# de botella.
#
# De ahi que `diagnosticar` NO avise por recibir YUY2: avisa por FPS bajos,
# y solo entonces senala el formato como causa probable. Un formato sin
# comprimir que mantiene el ritmo pedido no es un problema, es el mejor caso.
#
# El orden de las llamadas importa: hay que fijar el FOURCC ANTES que ancho
# y alto. Al reves, muchos backends ya han negociado el modo y lo descartan.
FOURCC_MJPG = cv2.VideoWriter_fourcc(*"MJPG")

# Bytes por pixel de los formatos sin comprimir habituales en webcams UVC.
# Sirve para calcular el ancho de banda que pide el bus cuando hay que
# explicar por que se cayeron los FPS.
_BYTES_POR_PIXEL = {"YUY2": 2, "YUYV": 2, "UYVY": 2, "NV12": 1.5, "I420": 1.5}

# Ancho de banda util aproximado de un USB 2.0 en MB/s. No son los 60 MB/s
# teoricos: el protocolo y el resto de dispositivos del bus se llevan lo suyo.
_USB2_MB_S = 35

# Frames que se descartan antes de medir los FPS reales. Las primeras
# lecturas tras abrir la camara no son representativas: el auto-exposure y
# el auto-foco todavia estan estabilizando.
_FRAMES_CALENTAMIENTO = 5

# Frames sobre los que se mide el ritmo real de la camara.
_FRAMES_MEDICION = 15

# Por debajo de esta fraccion de los FPS pedidos se considera que la camara
# no concedio lo solicitado y se avisa. 0.6 deja pasar la variacion normal
# de una webcam (pedir 30 y dar 24 es corriente) pero detecta el desplome a
# 8-10 FPS que delata una negociacion en YUYV.
_FRACCION_FPS_ACEPTABLE = 0.6


def describir_fourcc(valor):
    """
    Traduce el entero que devuelve CAP_PROP_FOURCC a sus 4 letras.

    OpenCV empaqueta el formato en un int de 32 bits, un byte por caracter.
    Sin esto el diagnostico imprimiria "1196444237" en vez de "MJPG".
    """
    try:
        codigo = int(valor)
    except (TypeError, ValueError):
        return "?"

    if codigo <= 0:
        return "?"

    letras = "".join(chr((codigo >> desplaz) & 0xFF) for desplaz in (0, 8, 16, 24))
    return letras if letras.isprintable() else "?"


def diagnosticar(pedido, real, fourcc, fps_medido, fps_pedido=None):
    """
    Compara lo que se pidio a la camara con lo que de verdad entrego.

    Se separa de `conectar` para poder probarla sin webcam: recibe numeros
    y devuelve texto.

    El criterio es el ritmo, no el formato. Recibir YUY2 en vez de MJPG no
    es un defecto mientras la camara mantenga los FPS —de hecho ahorra el
    coste de decodificar el JPEG—, asi que avisar de ello seria enviar al
    usuario a perseguir un problema que no tiene. Solo cuando los FPS caen
    se senala el formato, que entonces si es la causa probable.

    Args:
        pedido: (ancho, alto) solicitado.
        real: (ancho, alto) del primer frame leido de verdad. Se mide del
            frame y no de CAP_PROP_FRAME_WIDTH porque algunos drivers
            responden el valor que les pediste aunque esten entregando otro.
        fourcc: entero de CAP_PROP_FOURCC.
        fps_medido: ritmo real observado, o None si no se midio.
        fps_pedido: FPS solicitados (CAMARA_FPS por defecto).

    Returns:
        Lista de lineas de aviso. Vacia si no hay nada que corregir.
    """
    if fps_pedido is None:
        fps_pedido = CAMARA_FPS

    avisos = []
    formato = describir_fourcc(fourcc)
    ancho_real, alto_real = real

    # --- Resolucion ---
    if tuple(real) != tuple(pedido):
        avisos.append(
            f"La camara no concedio {pedido[0]}x{pedido[1]}: entrega "
            f"{ancho_real}x{alto_real}."
        )
        if ancho_real <= 640:
            # Caer a 640 no es "un poco peor": devuelve el sistema al
            # comportamiento anterior, porque el pipeline solo reduce el
            # frame si supera ANCHO_DETECCION. El embedding volveria a
            # salir de la imagen pequena.
            avisos.append(
                "   A 640 de ancho el embedding vuelve a salir del frame "
                "reducido, que es justo lo que queriamos evitar."
            )
        avisos.append(
            "   Prueba otra resolucion con CAMARA_ANCHO/CAMARA_ALTO en .env "
            "(p.ej. 1280x720)."
        )

    # --- Ritmo, y solo si cae, el formato como causa ---
    if fps_medido is not None and fps_medido < fps_pedido * _FRACCION_FPS_ACEPTABLE:
        avisos.append(
            f"Ritmo real {fps_medido:.1f} FPS, muy por debajo de los "
            f"{fps_pedido} pedidos."
        )

        bytes_px = _BYTES_POR_PIXEL.get(formato)
        if bytes_px:
            mb_s = ancho_real * alto_real * bytes_px * fps_pedido / 1e6
            avisos.append(
                f"   La camara entrega {formato}, sin comprimir: a "
                f"{ancho_real}x{alto_real} son ~{mb_s:.0f} MB/s y un USB 2.0 "
                f"da ~{_USB2_MB_S}."
            )
            avisos.append(
                "   Baja CAMARA_ANCHO/CAMARA_ALTO, o pasa la camara a un "
                "puerto USB 3.0."
            )
        else:
            avisos.append(
                "   Revisa el cable y el puerto, o baja "
                "CAMARA_ANCHO/CAMARA_ALTO."
            )

    return avisos


class CamaraSimulada:

    # Esta camara no mide profundidad. El pipeline lo consulta para decidir
    # si puede ejecutar el verificador 3D y para no reportar metricas 3D
    # inventadas a Supabase.
    profundidad_real = False

    def __init__(self, ancho=None, alto=None, fps=None):
        self.ancho_pedido = CAMARA_ANCHO if ancho is None else ancho
        self.alto_pedido = CAMARA_ALTO if alto is None else alto
        self.fps_pedido = CAMARA_FPS if fps is None else fps

        # Resolucion realmente concedida; se rellena al conectar.
        self.resolucion = None

        self.webcam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.webcam.isOpened():
            # Fallback sin DirectShow (Linux/macOS, o Windows sin DShow)
            self.webcam = cv2.VideoCapture(0)
        if not self.webcam.isOpened():
            raise RuntimeError("No se detecto webcam")

        # ORDEN DELIBERADO: formato primero, luego resolucion.
        self.webcam.set(cv2.CAP_PROP_FOURCC, FOURCC_MJPG)
        self.webcam.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho_pedido)
        self.webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto_pedido)
        self.webcam.set(cv2.CAP_PROP_FPS, self.fps_pedido)

        # Reducir buffer interno de la webcam a 1 frame (menor latencia)
        self.webcam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _medir_ritmo(self):
        """
        Mide los FPS reales leyendo frames de verdad.

        No se usa CAP_PROP_FPS: devuelve lo que la camara dice que hace, no
        lo que hace. El desplome por negociar un formato sin comprimir solo
        se ve cronometrando lecturas reales.

        Returns:
            (fps_medido, alto, ancho) del ultimo frame, o (None, None, None).
        """
        for _ in range(_FRAMES_CALENTAMIENTO):
            self.webcam.read()

        frame = None
        inicio = time.perf_counter()
        leidos = 0
        for _ in range(_FRAMES_MEDICION):
            ok, actual = self.webcam.read()
            if not ok:
                break
            frame = actual
            leidos += 1
        transcurrido = time.perf_counter() - inicio

        if leidos == 0 or transcurrido <= 0 or frame is None:
            return None, None, None

        alto, ancho = frame.shape[:2]
        return leidos / transcurrido, alto, ancho

    def conectar(self):
        fps_medido, alto_real, ancho_real = self._medir_ritmo()

        if ancho_real is None:
            raise RuntimeError(
                "La webcam se abrio pero no entrega frames. "
                "Revisa que no la tenga ocupada otra aplicacion."
            )

        self.resolucion = (ancho_real, alto_real)
        fourcc = self.webcam.get(cv2.CAP_PROP_FOURCC)
        formato = describir_fourcc(fourcc)

        ritmo = f"{fps_medido:.1f} FPS" if fps_medido else "FPS desconocidos"
        print(f" Camara SIMULADA conectada ({ancho_real}x{alto_real} "
              f"{formato}, {ritmo}, sin profundidad)")

        if ancho_real > 640:
            print("    El embedding se recorta del frame nativo; la deteccion "
                  "y el preview siguen a 640.")

        print("    Anti-spoofing 3D NO disponible en este modo.")
        print("    Prueba de vida por parpadeo (liveness 2D).")

        for linea in diagnosticar(
            (self.ancho_pedido, self.alto_pedido),
            (ancho_real, alto_real),
            fourcc,
            fps_medido,
            self.fps_pedido,
        ):
            print(f"    {linea}")

    def obtener_frames(self):
        """Retorna (color, None). No hay mapa de profundidad que devolver."""
        ret, frame = self.webcam.read()
        if not ret:
            return None, None
        return frame, None

    def cerrar(self):
        self.webcam.release()
        print(" Camara simulada cerrada")
