"""Estado thread-safe para el modo de registro biométrico."""

import threading


class EstadoRegistro:
    """Wrapper thread-safe para el estado de registro de usuarios."""

    def __init__(self):
        self._lock = threading.Lock()
        self._activo = False
        self._nombre = ""
        self._embeddings = []
        self._paso = 0
        self._completado = False
        self._resultado = {}
        self._recargar_cache = False

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

    def iniciar(self, nombre):
        """Inicia un nuevo registro."""
        with self._lock:
            self._activo = True
            self._nombre = nombre
            self._embeddings = []
            self._paso = 0
            self._completado = False
            self._resultado = {}

    def completar(self, resultado):
        """Marca el registro como completado."""
        with self._lock:
            self._activo = False
            self._completado = True
            self._resultado = resultado

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
                "paso": self._paso
            }
