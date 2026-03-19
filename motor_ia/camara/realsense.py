"""Cámara Intel RealSense D435i."""

import pyrealsense2 as rs
import numpy as np


class CamaraRealSense:

    def __init__(self):
        self.pipeline = None
        self.align = None

    def conectar(self):
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

        self.pipeline.start(config)
        self.align = rs.align(rs.stream.color)

        for _ in range(30):
            self.pipeline.wait_for_frames()

        print("✅ Cámara RealSense conectada")

    def obtener_frames(self):
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=5000)
            frames = self.align.process(frames)

            color = frames.get_color_frame()
            depth = frames.get_depth_frame()

            if not color or not depth:
                return None, None

            return (
                np.asanyarray(color.get_data()),
                np.asanyarray(depth.get_data())
            )
        except RuntimeError:
            return None, None

    def cerrar(self):
        if self.pipeline:
            self.pipeline.stop()
            print("📷 RealSense cerrada")
