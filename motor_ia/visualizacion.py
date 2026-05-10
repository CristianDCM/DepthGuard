"""Módulo de visualización para preview de debug."""

import cv2


def dibujar_preview(frame, bbox, es_real, es_dist, motivo, metricas,
                    nombre_reconocido, confianza, modo_registro_activo):
    """Dibuja overlays de debug sobre el frame para la ventana de preview."""
    vista = frame.copy()

    if bbox is not None:
        x, y, x2, y2 = bbox

        # Color del bbox según estado
        if modo_registro_activo:
            color_bbox = (255, 165, 0)  # Naranja - registro
            etiqueta = "REGISTRO"
        elif not es_real and not es_dist:
            color_bbox = (0, 0, 255)  # Rojo - fraude
            etiqueta = f"FRAUDE: {motivo}"
        elif es_dist:
            color_bbox = (0, 165, 255)  # Naranja - distancia
            etiqueta = motivo
        elif nombre_reconocido:
            color_bbox = (0, 255, 0)  # Verde - reconocido
            etiqueta = f"{nombre_reconocido} ({confianza * 100:.1f}%)"
        elif es_real:
            color_bbox = (0, 255, 255)  # Amarillo - real pero no reconocido
            etiqueta = "Persona no registrada"
        else:
            color_bbox = (128, 128, 128)  # Gris
            etiqueta = "Analizando..."

        # Dibujar bbox
        cv2.rectangle(vista, (x, y), (x2, y2), color_bbox, 2)

        # Fondo para etiqueta
        tam, _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(vista, (x, y - 28), (x + tam[0] + 8, y), color_bbox, -1)
        cv2.putText(vista, etiqueta, (x + 4, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Métricas en esquina inferior
        if metricas:
            y_met = vista.shape[0] - 10
            textos = []
            if "distancia" in metricas:
                textos.append(f"Dist: {metricas['distancia']}cm")
            if "varianza" in metricas:
                textos.append(f"Var: {metricas['varianza']}")
            if "rango_3d" in metricas:
                textos.append(f"Rango: {metricas['rango_3d']}")
            if "direccion" in metricas:
                textos.append(f"Dir: {metricas['direccion']}")

            info = " | ".join(textos)
            cv2.putText(vista, info, (10, y_met),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # Título
    cv2.putText(vista, "DEPTHGUARD - Preview", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    return vista


def mostrar_preview(vista):
    """Muestra el frame en ventana y retorna True si se presiona 'q'."""
    cv2.imshow("DepthGuard - Preview", vista)
    return (cv2.waitKey(1) & 0xFF == ord('q'))
