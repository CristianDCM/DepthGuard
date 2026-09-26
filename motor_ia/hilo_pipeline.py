"""
Hilo del pipeline de IA que recuerda POR QUE termino.

El pipeline es la unica parte de DepthGuard que reconoce a alguien. Si muere,
los demas hilos (heartbeat, WebRTC, comandos) siguen funcionando y la web ve
el sistema "en linea" mientras no se concede ni se registra nada. iniciar.py
vigila este hilo y detiene el proceso cuando termina:

  - error:   codigo 1, para que quien lo supervise (INICIAR.bat, la tarea
             programada de la fase 5) lo note y pueda reiniciarlo.
  - sin error (se pulso 'q' en el preview): codigo 0, apagado normal.
"""

import threading


class HiloPipeline(threading.Thread):

    def __init__(self, objetivo, *args, **kwargs):
        super().__init__(daemon=True, name="pipeline-ia")
        self._objetivo = objetivo
        self._args = args
        self._kwargs = kwargs
        self.error = None

    def run(self):
        try:
            self._objetivo(*self._args, **self._kwargs)
        # BaseException: tambien un SystemExit (face_recognition llama a quit()
        # si no encuentra sus modelos) debe contar como fallo, no como 'q'.
        except BaseException as e:  # noqa: BLE001
            self.error = e
