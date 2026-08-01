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


def dibujar_preview(frame, tracks, modo_registro_activo, registro_info=None):
    """Dibuja overlays de debug sobre el frame para la ventana de preview.
    
    tracks: lista de dicts con info de cada persona detectada:
        - bbox: (x, y, x2, y2)
        - es_real: bool
        - es_dist: bool
        - motivo: str
        - metricas: dict
        - nombre: str o None
        - confianza: float
    
    registro_info: dict opcional con info del registro en curso
    """
    vista = frame.copy()

    # Dibujar cada persona detectada
    for track in tracks:
        _dibujar_persona(vista, track, modo_registro_activo and registro_info is not None)

    # Título
    cv2.putText(vista, "DEPTHGUARD - Preview", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Panel de registro (solo si está activo)
    if modo_registro_activo and registro_info:
        _dibujar_panel_registro(vista, registro_info)

    return vista


def _dibujar_persona(vista, track, en_registro):
    """Dibuja bbox y etiqueta para una persona."""
    bbox = track.get("bbox")
    if bbox is None:
        return

    x, y, x2, y2 = bbox
    es_real = track.get("es_real", True)
    es_dist = track.get("es_dist", False)
    motivo = track.get("motivo", "")
    nombre = track.get("nombre")
    confianza = track.get("confianza", 0)
    metricas = track.get("metricas", {})
    reg_info = track.get("registro_info")

    # Color del bbox según estado
    if en_registro and reg_info:
        angulo_ok = reg_info.get("angulo_ok", False)
        captura_reciente = reg_info.get("captura_reciente", False)

        if captura_reciente:
            color_bbox = (0, 255, 0)
            etiqueta = f"CAPTURADO {reg_info.get('paso', 0)}/5"
        elif angulo_ok:
            color_bbox = (0, 255, 255)
            t_estable = reg_info.get("tiempo_estable", 0)
            etiqueta = f"Mantenga la pose... {t_estable:.1f}s"
        else:
            color_bbox = (255, 165, 0)
            etiqueta = "REGISTRO"
    elif en_registro:
        color_bbox = (255, 165, 0)
        etiqueta = "REGISTRO"
    elif not es_real and not es_dist:
        color_bbox = (0, 0, 255)
        etiqueta = f"FRAUDE: {motivo}"
    elif es_dist:
        color_bbox = (0, 165, 255)
        etiqueta = motivo
    elif nombre:
        color_bbox = (0, 255, 0)
        etiqueta = f"{nombre} ({confianza * 100:.1f}%)"
    elif es_real:
        color_bbox = (0, 255, 255)
        etiqueta = "Persona no registrada"
    else:
        color_bbox = (128, 128, 128)
        etiqueta = "Analizando..."

    # Dibujar bbox
    cv2.rectangle(vista, (x, y), (x2, y2), color_bbox, 2)

    # Fondo para etiqueta
    tam, _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(vista, (x, y - 28), (x + tam[0] + 8, y), color_bbox, -1)
    cv2.putText(vista, etiqueta, (x + 4, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    # Métricas debajo del bbox de cada persona
    if metricas and not en_registro:
        textos = []
        if "distancia" in metricas:
            textos.append(f"Dist:{metricas['distancia']}cm")
        if "direccion" in metricas:
            textos.append(f"Dir:{metricas['direccion']}")
        if textos:
            info_text = " | ".join(textos)
            cv2.putText(vista, info_text, (x, y2 + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_bbox, 1)


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
            cv2.circle(vista, (cx, cy), 16, (0, 200, 0), -1)
            cv2.circle(vista, (cx, cy), 16, (0, 255, 0), 2)
        elif ang_n == angulo:
            cv2.circle(vista, (cx, cy), 16, (0, 180, 255), -1)
            cv2.circle(vista, (cx, cy), 16, (0, 255, 255), 2)
        else:
            cv2.circle(vista, (cx, cy), 16, (60, 60, 60), -1)
            cv2.circle(vista, (cx, cy), 16, (100, 100, 100), 2)

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
