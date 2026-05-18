"""Módulo de visualización para preview de debug."""

import cv2
import time

# Mapa de instrucciones por ángulo solicitado
_INSTRUCCIONES_ANGULO = {
    "frontal":   "Mire al FRENTE",
    "izquierda": "Gire a su IZQUIERDA",
    "derecha":   "Gire a su DERECHA",
    "arriba":    "Mire hacia ARRIBA",
    "abajo":     "Mire hacia ABAJO",
}

# Flechas Unicode para indicar dirección
_FLECHAS_ANGULO = {
    "frontal":   "O",
    "izquierda": "<<",
    "derecha":   ">>",
    "arriba":    "^^",
    "abajo":     "vv",
}


def dibujar_preview(frame, bbox, es_real, es_dist, motivo, metricas,
                    nombre_reconocido, confianza, modo_registro_activo,
                    registro_info=None):
    """Dibuja overlays de debug sobre el frame para la ventana de preview.
    
    registro_info: dict opcional con info del registro en curso:
        - angulo_solicitado: str ("frontal", "izquierda", etc.)
        - paso: int (1-5)
        - estabilizado: bool (si la persona mantiene la pose)
        - tiempo_estable: float (segundos que lleva estable)
        - captura_reciente: bool (flash de captura exitosa)
    """
    vista = frame.copy()

    if bbox is not None:
        x, y, x2, y2 = bbox

        # Color del bbox según estado
        if modo_registro_activo and registro_info:
            # Modo registro con guiado de ángulos
            info = registro_info
            angulo_ok = info.get("angulo_ok", False)
            captura_reciente = info.get("captura_reciente", False)

            if captura_reciente:
                color_bbox = (0, 255, 0)  # Verde flash = captura exitosa
                etiqueta = f"CAPTURADO {info.get('paso', 0)}/5"
            elif angulo_ok:
                color_bbox = (0, 255, 255)  # Amarillo = ángulo correcto, estabilizando
                t_estable = info.get("tiempo_estable", 0)
                etiqueta = f"Mantenga la pose... {t_estable:.1f}s"
            else:
                color_bbox = (255, 165, 0)  # Naranja = esperando ángulo
                etiqueta = "REGISTRO"
        elif modo_registro_activo:
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

            info_text = " | ".join(textos)
            cv2.putText(vista, info_text, (10, y_met),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # Título
    cv2.putText(vista, "DEPTHGUARD - Preview", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # === PANEL DE REGISTRO ===
    if modo_registro_activo and registro_info:
        _dibujar_panel_registro(vista, registro_info)

    return vista


def _dibujar_panel_registro(vista, info):
    """Dibuja el panel de instrucciones de registro en la parte superior."""
    h, w = vista.shape[:2]
    angulo = info.get("angulo_solicitado", "frontal")
    paso = info.get("paso", 0)
    angulo_ok = info.get("angulo_ok", False)
    nombre = info.get("nombre", "")
    captura_reciente = info.get("captura_reciente", False)

    # Fondo semitransparente para el panel
    overlay = vista.copy()
    panel_h = 110
    cv2.rectangle(overlay, (0, 30), (w, 30 + panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, vista, 0.3, 0, vista)

    # Nombre del usuario
    cv2.putText(vista, f"Registrando: {nombre}", (10, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    # Progreso: circulos para cada ángulo
    angulos_nombres = ["frontal", "izquierda", "derecha", "arriba", "abajo"]
    angulos_labels = ["F", "I", "D", "Ar", "Ab"]
    angulos_cap = info.get("angulos_capturados", [])

    base_x = 10
    for i, (ang_n, ang_l) in enumerate(zip(angulos_nombres, angulos_labels)):
        cx = base_x + i * 55 + 20
        cy = 85

        if ang_n in angulos_cap:
            # Capturado - verde
            cv2.circle(vista, (cx, cy), 16, (0, 200, 0), -1)
            cv2.circle(vista, (cx, cy), 16, (0, 255, 0), 2)
        elif ang_n == angulo:
            # Actual - amarillo pulsante
            cv2.circle(vista, (cx, cy), 16, (0, 180, 255), -1)
            cv2.circle(vista, (cx, cy), 16, (0, 255, 255), 2)
        else:
            # Pendiente - gris
            cv2.circle(vista, (cx, cy), 16, (60, 60, 60), -1)
            cv2.circle(vista, (cx, cy), 16, (100, 100, 100), 2)

        # Letra del ángulo
        tam_l, _ = cv2.getTextSize(ang_l, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.putText(vista, ang_l, (cx - tam_l[0] // 2, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    # Instrucción principal grande
    instruccion = _INSTRUCCIONES_ANGULO.get(angulo, "")
    flecha = _FLECHAS_ANGULO.get(angulo, "")

    if captura_reciente:
        texto_inst = f"CAPTURADO! Paso {paso}/5"
        color_inst = (0, 255, 0)
    elif angulo_ok:
        texto_inst = f"{instruccion} - Mantenga..."
        color_inst = (0, 255, 255)
    else:
        texto_inst = f"{flecha}  {instruccion}  {flecha}   (Paso {paso + 1}/5)"
        color_inst = (0, 165, 255)

    cv2.putText(vista, texto_inst, (10, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_inst, 2)


def mostrar_preview(vista):
    """Muestra el frame en ventana y retorna True si se presiona 'q'."""
    cv2.imshow("DepthGuard - Preview", vista)
    return (cv2.waitKey(1) & 0xFF == ord('q'))
