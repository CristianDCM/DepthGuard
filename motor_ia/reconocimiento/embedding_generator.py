"""Genera y compara embeddings faciales."""

import numpy as np
import face_recognition
from config.settings import TOLERANCIA_FACIAL


class ReconocedorFacial:

    def __init__(self):
        self.cache = []

    def generar_embedding(self, imagen_rgb, bbox):
        """Genera vector 128D del rostro."""
        x, y, x2, y2 = bbox
        ubicacion = [(y, x2, y2, x)]

        encodings = face_recognition.face_encodings(imagen_rgb, ubicacion, model="small")

        if encodings:
            return encodings[0]
        return None

    def buscar(self, embedding):
        """Busca en la caché."""
        mejor_dist = float("inf")
        mejor_nombre = None
        emb = np.array(embedding)

        for item in self.cache:
            dist = np.linalg.norm(emb - item["embedding"])
            if dist < TOLERANCIA_FACIAL and dist < mejor_dist:
                mejor_dist = dist
                mejor_nombre = item["nombre"]

        if mejor_nombre:
            return mejor_nombre, round((1 - mejor_dist) * 100, 1)

        return None, 0

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
                    "nombre": usuario["nombre"],
                    "embedding": np.array(emb)
                })

        print(f"   📦 Caché: {len(self.cache)} embeddings")

    def recargar_cache(self, usuarios):
        """Alias para actualizar después de registrar."""
        self.cargar_cache(usuarios)
