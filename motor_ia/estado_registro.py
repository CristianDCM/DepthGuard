"""Estado thread-safe para el modo de registro biométrico."""

import threading
import time


# Secuencia de ángulos requeridos para un registro completo
ANGULOS_REGISTRO = ["frontal", "izquierda", "derecha", "arriba", "abajo"]


class EstadoRegistro:
    """Wrapper thread-safe para el estado de registro de usuarios.
    
    Gestiona la secuencia de captura de 5 ángulos faciales:
    frontal → izquierda → derecha → arriba → abajo
    
    El pipeline solo captura un embedding cuando la dirección detectada
    coincide con el ángulo solicitado.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._activo = False
        self._nombre = ""
        self._embeddings = []
        self._paso = 0
        self._completado = False
        self._resultado = {}
        self._recargar_cache = False
        # Nuevo: tracking de ángulos capturados
        self._angulo_solicitado = ""
        self._angulos_capturados = []
        self._ultimo_captura = 0  # timestamp de la última captura
        self._estabilizado = False  # si la persona mantiene la pose
        self._tiempo_estable = 0  # cuánto tiempo lleva estable en la dirección

    @property
    def activo(self):
        with self._lock:
            return self._activo

    @activo.setter
    def activo(self, valor):
        with self._lock:
            self._activo = valor

    @property
    def nombre(self):
        with self._lock:
            return self._nombre

    @nombre.setter
    def nombre(self, valor):
        with self._lock:
            self._nombre = valor

    @property
    def embeddings(self):
        with self._lock:
            return list(self._embeddings)

    @embeddings.setter
    def embeddings(self, valor):
        with self._lock:
            self._embeddings = valor

    def agregar_embedding(self, emb):
        with self._lock:
            self._embeddings.append(emb)

    @property
    def paso(self):
        with self._lock:
            return self._paso

    @paso.setter
    def paso(self, valor):
        with self._lock:
            self._paso = valor

    @property
    def completado(self):
        with self._lock:
            return self._completado

    @completado.setter
    def completado(self, valor):
        with self._lock:
            self._completado = valor

    @property
    def resultado(self):
        with self._lock:
            return dict(self._resultado)

    @resultado.setter
    def resultado(self, valor):
        with self._lock:
            self._resultado = valor

    @property
    def recargar_cache(self):
        with self._lock:
            return self._recargar_cache

    @recargar_cache.setter
    def recargar_cache(self, valor):
        with self._lock:
            self._recargar_cache = valor

    @property
    def angulo_solicitado(self):
        with self._lock:
            return self._angulo_solicitado

    @angulo_solicitado.setter
    def angulo_solicitado(self, valor):
        with self._lock:
            self._angulo_solicitado = valor

    @property
    def angulos_capturados(self):
        with self._lock:
            return list(self._angulos_capturados)

    @property
    def estabilizado(self):
        with self._lock:
            return self._estabilizado

    @estabilizado.setter
    def estabilizado(self, valor):
        with self._lock:
            self._estabilizado = valor

    @property
    def tiempo_estable(self):
        with self._lock:
            return self._tiempo_estable

    @tiempo_estable.setter
    def tiempo_estable(self, valor):
        with self._lock:
            self._tiempo_estable = valor

    def iniciar(self, nombre):
        """Inicia un nuevo registro con secuencia de ángulos."""
        with self._lock:
            self._activo = True
            self._nombre = nombre
            self._embeddings = []
            self._paso = 0
            self._completado = False
            self._resultado = {}
            self._angulos_capturados = []
            self._angulo_solicitado = ANGULOS_REGISTRO[0]  # Empieza con "frontal"
            self._ultimo_captura = 0
            self._estabilizado = False
            self._tiempo_estable = 0

    def registrar_captura(self, embedding, angulo):
        """Registra una captura exitosa de un ángulo específico."""
        with self._lock:
            self._embeddings.append(embedding)
            self._angulos_capturados.append(angulo)
            self._paso = len(self._embeddings)
            self._ultimo_captura = time.time()
            self._estabilizado = False
            self._tiempo_estable = 0

            # Avanzar al siguiente ángulo
            idx_siguiente = len(self._angulos_capturados)
            if idx_siguiente < len(ANGULOS_REGISTRO):
                self._angulo_solicitado = ANGULOS_REGISTRO[idx_siguiente]
            # Si ya completó todos, angulo_solicitado queda en el último

    def puede_capturar(self):
        """Verifica si pasó suficiente tiempo desde la última captura (cooldown entre ángulos)."""
        with self._lock:
            if self._ultimo_captura == 0:
                return True
            return (time.time() - self._ultimo_captura) >= 1.5  # 1.5s entre capturas

    def completar(self, resultado):
        """Marca el registro como completado."""
        with self._lock:
            self._activo = False
            self._completado = True
            self._resultado = resultado
            self._angulo_solicitado = ""
            self._estabilizado = False

    def obtener_estado(self):
        """Retorna snapshot del estado actual."""
        with self._lock:
            if self._completado:
                resultado = dict(self._resultado)
                self._completado = False
                return {"completado": True, "datos": resultado}
            return {
                "completado": False,
                "activo": self._activo,
                "paso": self._paso,
                "angulo_solicitado": self._angulo_solicitado,
                "angulos_capturados": list(self._angulos_capturados),
            }
