"""Anti-spoofing 3D con umbrales calibrados."""

import numpy as np
from config.settings import (
    UMBRAL_VARIANZA, UMBRAL_RANGO_PROF,
    RANGO_DIST_MIN, RANGO_DIST_MAX,
    MIN_PIXELES_VALIDOS
)


class VerificadorAntiSpoofing:

    def verificar(self, mapa_profundidad, bbox):
        """
        Retorna (es_real, es_distancia, motivo, metricas).
        """
        x, y, x2, y2 = bbox

        margen_v = int((y2 - y) * 0.15)
        margen_h = int((x2 - x) * 0.15)

        t = max(0, y + margen_v)
        b = min(mapa_profundidad.shape[0], y2 - margen_v)
        l = max(0, x + margen_h)
        r = min(mapa_profundidad.shape[1], x2 - margen_h)

        region = mapa_profundidad[t:b, l:r].astype(float) / 10.0
        validos = region[region > 0]

        total = region.size
        n_validos = len(validos)
        porcentaje = n_validos / max(total, 1)

        if n_validos < 100:
            return False, False, "Sin datos 3D", {}

        varianza = np.var(validos)
        distancia = np.median(validos)
        p5 = np.percentile(validos, 5)
        p95 = np.percentile(validos, 95)
        rango = p95 - p5

        metricas = {
            "varianza": round(varianza, 2),
            "distancia": round(distancia, 1),
            "rango_3d": round(rango, 1),
            "pixeles_validos": round(porcentaje, 3)
        }

        if porcentaje < MIN_PIXELES_VALIDOS:
            return False, False, "Pocos datos", metricas
        elif distancia < RANGO_DIST_MIN:
            return False, True, f"Muy cerca ({distancia:.0f}cm)", metricas
        elif distancia > RANGO_DIST_MAX:
            return False, True, f"Muy lejos ({distancia:.0f}cm)", metricas
        elif varianza < UMBRAL_VARIANZA:
            return False, False, "Superficie plana", metricas
        elif rango < UMBRAL_RANGO_PROF:
            return False, False, "Sin volumen 3D", metricas

        return True, False, "Verificado OK", metricas
