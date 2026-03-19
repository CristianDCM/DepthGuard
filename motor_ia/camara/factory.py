"""Fábrica de cámaras. Elige según .env"""

from config.settings import MODO_CAMARA


def crear_camara():
    if MODO_CAMARA == "realsense":
        from motor_ia.camara.realsense import CamaraRealSense
        return CamaraRealSense()
    else:
        from motor_ia.camara.simulada import CamaraSimulada
        return CamaraSimulada()
