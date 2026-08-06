"""Genera y compara embeddings faciales."""

import cv2
import numpy as np
import face_recognition
from config.settings import TOLERANCIA_FACIAL


class ReconocedorFacial:

    def __init__(self):
        self.cache = []
        # CLAHE: ecualización adaptativa de histograma
        # Normaliza iluminación desigual (sombras, contraluz, etc.)
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

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

    def generar_embedding(self, imagen_rgb, bbox):
        """
        Genera vector 128D del rostro.
        Usa model='large' (68 landmarks) para alineación más precisa
        y CLAHE para normalizar iluminación.
        """
        x, y, x2, y2 = bbox

        # Preprocesar: normalizar iluminación del rostro
        imagen_mejorada = self._preprocesar_rostro(imagen_rgb, bbox)

        ubicacion = [(y, x2, y2, x)]

        encodings = face_recognition.face_encodings(
            imagen_mejorada, ubicacion, model="large"
        )

        if encodings:
            return encodings[0]
        return None

    def buscar(self, embedding):
        """Busca en la caché. Retorna (nombre, confianza, usuario_id)."""
        mejor_dist = float("inf")
        mejor_nombre = None
        mejor_id = None
        emb = np.array(embedding)

        for item in self.cache:
            dist = np.linalg.norm(emb - item["embedding"])
            if dist < TOLERANCIA_FACIAL and dist < mejor_dist:
                mejor_dist = dist
                mejor_nombre = item["nombre"]
                mejor_id = item["id"]

        if mejor_nombre:
            return mejor_nombre, round(1 - mejor_dist, 4), mejor_id

        return None, 0.0, None

    def cargar_cache(self, usuarios):
        """Carga embeddings de usuarios a memoria."""
        self.cache = []

        for usuario in usuarios:
            if "embeddings" in usuario:
                lista = usuario["embeddings"]
            elif "embedding" in usuario:
                lista = [usuario["embedding"]]
            else:
                continue

            for emb in lista:
                self.cache.append({
                    "id": usuario.get("id"),
                    "nombre": usuario["nombre"],
                    "embedding": np.array(emb)
                })

        print(f"    Caché: {len(self.cache)} embeddings")

    def recargar_cache(self, usuarios):
        """Alias para actualizar después de registrar."""
        self.cargar_cache(usuarios)

