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

# Indicadores de dirección (limpios, sin flechas amateur)
_FLECHAS_ANGULO = {
    "frontal":   "",
    "izquierda": "",
    "derecha":   "",
    "arriba":    "",
    "abajo":     "",
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

    # (Título de preview removido para mantener estética limpia)
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
            color_bbox = (50, 255, 50) # Verde neón suave
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
        color_bbox = (30, 30, 255) # Rojo vibrante
        etiqueta = f"FRAUDE: {motivo}"
    elif es_dist:
        color_bbox = (0, 165, 255) # Naranja alerta
        etiqueta = motivo
    elif nombre:
        color_bbox = (50, 255, 50) # Verde neón suave
        etiqueta = f"{nombre} ({confianza * 100:.1f}%)"
    elif es_real:
        color_bbox = (0, 255, 255)
        etiqueta = "Persona no registrada"
    else:
        color_bbox = (150, 150, 150)
        etiqueta = "Analizando..."

    # Extraer dimensiones de la pantalla para evitar que los textos salgan del frame
    img_h, img_w = vista.shape[:2]

    # 1. Dibujar Bounding Box estilo HUD Táctico (Esquinas)
    _dibujar_esquinas(vista, x, y, x2, y2, color_bbox, 2)

    # 2. Retículo central de profundidad (Crosshair)
    cx, cy = x + (x2 - x) // 2, y + (y2 - y) // 2
    cv2.line(vista, (cx - 6, cy), (cx + 6, cy), color_bbox, 1, cv2.LINE_AA)
    cv2.line(vista, (cx, cy - 6), (cx, cy + 6), color_bbox, 1, cv2.LINE_AA)

    # 3. Etiqueta Superior (Nombre/Estado)
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = 0.5
    tam, _ = cv2.getTextSize(etiqueta, font, font_scale, 1)
    
    # Clamping superior: Evitar que se pierda por arriba o por la derecha
    label_y = y
    if label_y - tam[1] - 14 < 0:
        label_y = tam[1] + 14
        
    label_x = x
    if label_x + tam[0] + 12 > img_w:
        label_x = img_w - tam[0] - 12
    if label_x < 0: label_x = 0

    # Fondo negro mate sólido para máximo contraste
    cv2.rectangle(vista, (label_x, label_y - tam[1] - 14), (label_x + tam[0] + 12, label_y), (15, 15, 15), -1)
    # Borde superior de acento
    cv2.line(vista, (label_x, label_y - tam[1] - 14), (label_x + tam[0] + 12, label_y - tam[1] - 14), color_bbox, 2, cv2.LINE_AA)
    
    # Texto con Anti-Aliasing
    cv2.putText(vista, etiqueta, (label_x + 6, label_y - 7), font, font_scale, color_bbox, 1, cv2.LINE_AA)

    # 4. Panel de Métricas Inferiores
    if metricas and not en_registro:
        textos = []
        if "distancia" in metricas:
            textos.append(f"Dist: {metricas['distancia']}cm")
        if "direccion" in metricas:
            textos.append(f"Dir: {metricas['direccion']}")
        if textos:
            info_text = " | ".join(textos)
            font_metrics = cv2.FONT_HERSHEY_SIMPLEX
            scale_m = 0.45
            tam_m, _ = cv2.getTextSize(info_text, font_metrics, scale_m, 1)
            
            # Clamping inferior: Evitar que se pierda por abajo o por la derecha
            metrics_y = y2
            if metrics_y + tam_m[1] + 14 > img_h:
                metrics_y = img_h - tam_m[1] - 14
                
            metrics_x = x
            if metrics_x + tam_m[0] + 12 > img_w:
                metrics_x = img_w - tam_m[0] - 12
            if metrics_x < 0: metrics_x = 0

            # Fondo negro mate inferior
            cv2.rectangle(vista, (metrics_x, metrics_y), (metrics_x + tam_m[0] + 12, metrics_y + tam_m[1] + 14), (15, 15, 15), -1)
            # Borde inferior de acento
            cv2.line(vista, (metrics_x, metrics_y + tam_m[1] + 14), (metrics_x + tam_m[0] + 12, metrics_y + tam_m[1] + 14), color_bbox, 1, cv2.LINE_AA)
            
            # Texto blanco para alta legibilidad
            cv2.putText(vista, info_text, (metrics_x + 6, metrics_y + tam_m[1] + 7),
                        font_metrics, scale_m, (255, 255, 255), 1, cv2.LINE_AA)

def _dibujar_esquinas(vista, x, y, x2, y2, color, thickness=2):
    """Dibuja un bounding box estilo HUD táctico (solo esquinas) para aspecto profesional."""
    w, h = x2 - x, y2 - y
    l = max(10, min(30, int(min(w, h) * 0.2))) # Longitud adaptable al tamaño del rostro
    
    # Superior izquierda
    cv2.line(vista, (x, y), (x + l, y), color, thickness, cv2.LINE_AA)
    cv2.line(vista, (x, y), (x, y + l), color, thickness, cv2.LINE_AA)
    # Superior derecha
    cv2.line(vista, (x2, y), (x2 - l, y), color, thickness, cv2.LINE_AA)
    cv2.line(vista, (x2, y), (x2, y + l), color, thickness, cv2.LINE_AA)
    # Inferior izquierda
    cv2.line(vista, (x, y2), (x + l, y2), color, thickness, cv2.LINE_AA)
    cv2.line(vista, (x, y2), (x, y2 - l), color, thickness, cv2.LINE_AA)
    # Inferior derecha
    cv2.line(vista, (x2, y2), (x2 - l, y2), color, thickness, cv2.LINE_AA)
    cv2.line(vista, (x2, y2), (x2, y2 - l), color, thickness, cv2.LINE_AA)


def _dibujar_panel_registro(vista, info):
    """Dibuja el panel de instrucciones de registro en la parte superior."""
    h, w = vista.shape[:2]
    angulo = info.get("angulo_solicitado", "frontal")
    paso = info.get("paso", 0)
    angulo_ok = info.get("angulo_ok", False)
    nombre = info.get("nombre", "")
    captura_reciente = info.get("captura_reciente", False)
    # ==========================================
    # HUD BIOMÉTRICO PROFESIONAL (OPENCV)
    # ==========================================
    
    h_frame, w = vista.shape[:2]
    
    # 1. Panel superior con gradiente oscuro
    overlay = vista.copy()
    panel_h = 90
    cv2.rectangle(overlay, (0, 0), (w, panel_h), (12, 12, 14), -1)
    # Línea separadora fina y sutil
    cv2.line(overlay, (0, panel_h), (w, panel_h), (40, 40, 40), 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.88, vista, 0.12, 0, vista)

    # 2. Barra de Progreso Segmentada
    angulos_nombres = ["frontal", "izquierda", "derecha", "arriba", "abajo"]
    angulos_cap = info.get("angulos_capturados", [])
    
    margen = 20
    ancho_total = w - (margen * 2)
    gap = 3
    ancho_seg = (ancho_total - gap * 4) // 5
    bar_y = 12
    bar_h = 4
    
    for i, ang_n in enumerate(angulos_nombres):
        x1 = margen + i * (ancho_seg + gap)
        x2 = x1 + ancho_seg
        
        if ang_n in angulos_cap:
            cv2.rectangle(vista, (x1, bar_y), (x2, bar_y + bar_h), (0, 230, 0), -1)
        elif ang_n == angulo:
            cv2.rectangle(vista, (x1, bar_y), (x2, bar_y + bar_h), (0, 200, 255), -1)
        else:
            cv2.rectangle(vista, (x1, bar_y), (x2, bar_y + bar_h), (50, 50, 50), -1)

    # 3. Nombre del usuario
    cv2.putText(vista, f"REGISTRO  |  {nombre.upper()}", (margen, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1, cv2.LINE_AA)

    # 4. Instrucción principal
    instruccion = _INSTRUCCIONES_ANGULO.get(angulo, "").upper()

    if captura_reciente:
        texto_inst = f"CAPTURA EXITOSA  [{paso}/5]"
        color_inst = (0, 255, 0)
    elif angulo_ok:
        texto_inst = "MANTENGA LA POSICION..."
        color_inst = (0, 255, 255)
    else:
        texto_inst = f"PASO {paso + 1}/5:  {instruccion}"
        color_inst = (0, 180, 255)

    cv2.putText(vista, texto_inst, (margen, 72),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, color_inst, 2, cv2.LINE_AA)

    # 5. Alerta de calidad (esquina inferior izquierda)
    calidad_error = info.get("calidad_error")
    if calidad_error:
        texto_err = calidad_error.upper()
        tam_e, _ = cv2.getTextSize(texto_err, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        err_y = h_frame - 15
        # Fondo rojo oscuro
        cv2.rectangle(vista, (margen - 5, err_y - tam_e[1] - 8), 
                      (margen + tam_e[0] + 10, err_y + 5), (0, 0, 120), -1)
        cv2.putText(vista, texto_err, (margen, err_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 255), 1, cv2.LINE_AA)


def mostrar_preview(vista):
    """Muestra el frame en ventana y retorna True si se presiona 'q'."""
    cv2.imshow("DepthGuard - Preview", vista)
    return (cv2.waitKey(1) & 0xFF == ord('q'))
