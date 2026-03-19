"""
Orquestador principal del Motor IA.
Cámara → Detección → Anti-spoofing → Reconocimiento
Envía resultados al Backend por queue.Queue
"""

import time
import cv2
import queue
import datetime
import os

from motor_ia.camara.factory import crear_camara
from motor_ia.deteccion.face_mesh import DetectorFaceMesh
from motor_ia.antispoofing.verificador_3d import VerificadorAntiSpoofing
from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial
from config.settings import (
    COOLDOWN_EMBEDDING, COOLDOWN_ANTISPOOFING,
    COOLDOWN_EVENTO, CAPTURAS_DIR
)


def _guardar_foto(imagen, prefijo):
    """Guarda captura y retorna ruta relativa."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{prefijo}_{timestamp}.jpg"
    ruta_completa = os.path.join(CAPTURAS_DIR, nombre)
    cv2.imwrite(ruta_completa, imagen)
    return f"/capturas/{nombre}"


def _dibujar_preview(frame, bbox, es_real, es_dist, motivo, metricas,
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
            etiqueta = f"{nombre_reconocido} ({confianza}%)"
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
            if "rango" in metricas:
                textos.append(f"Rango: {metricas['rango']}")
            if "direccion" in metricas:
                textos.append(f"Dir: {metricas['direccion']}")

            info = " | ".join(textos)
            cv2.putText(vista, info, (10, y_met),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # Título
    cv2.putText(vista, "DEPTHGUARD - Preview", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    return vista


def ejecutar_pipeline(cola_eventos, modo_registro, db_manager):
    """
    Bucle principal. Corre en un hilo separado.
    """

    # Crear componentes
    camara = crear_camara()
    detector = DetectorFaceMesh()
    antispoofing = VerificadorAntiSpoofing()
    reconocedor = ReconocedorFacial()

    # Conectar cámara con reintentos
    intentos = 0
    while True:
        try:
            camara.conectar()
            break
        except Exception as e:
            intentos += 1
            espera = min(intentos * 2, 30)
            print(f"❌ Cámara: {e}. Reintento en {espera}s...")
            time.sleep(espera)

    # Cargar usuarios
    usuarios = db_manager.obtener_todos_usuarios()
    reconocedor.cargar_cache(usuarios)

    # Timers
    t_embedding = 0
    t_spoofing = 0
    t_evento = 0

    # Cache
    spoofing_cache = None

    # Estado para preview
    nombre_actual = None
    confianza_actual = 0

    print("🟢 Pipeline IA activo")
    print("   📺 Ventana de preview abierta (presiona 'q' para cerrar)")

    try:
        while True:
            color, profundidad = camara.obtener_frames()

            if color is None:
                time.sleep(0.1)
                continue

            ahora = time.time()
            imagen_rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)

            # === DETECCIÓN (cada frame) ===
            encontrada, bbox, angulo, direccion = detector.detectar(imagen_rgb)

            if not encontrada:
                # Mostrar frame sin detección
                vista = color.copy()
                cv2.putText(vista, "DEPTHGUARD - Preview", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(vista, "Sin rostro detectado", (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
                cv2.imshow("DepthGuard - Preview", vista)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                time.sleep(0.05)
                continue

            # === ANTI-SPOOFING (cada 0.3s) ===
            if ahora - t_spoofing >= COOLDOWN_ANTISPOOFING:
                t_spoofing = ahora
                es_real, es_dist, motivo, metricas = antispoofing.verificar(
                    profundidad, bbox
                )
                metricas["angulo"] = angulo
                metricas["direccion"] = direccion
                spoofing_cache = (es_real, es_dist, motivo, metricas)

            if spoofing_cache is None:
                # Mostrar preview básico mientras se analiza
                vista = _dibujar_preview(
                    color, bbox, True, False, "Analizando...", {},
                    None, 0, modo_registro["activo"]
                )
                cv2.imshow("DepthGuard - Preview", vista)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            es_real, es_dist, motivo, metricas = spoofing_cache

            # === REGISTRO ===
            if modo_registro["activo"] and es_real:
                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                if embedding is not None:
                    cola_eventos.put({
                        "tipo": "REGISTRO_EMBEDDING",
                        "embedding": embedding,
                        "angulo": angulo,
                        "frame": color.copy()
                    })
                # Preview en modo registro
                vista = _dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    None, 0, True
                )
                cv2.imshow("DepthGuard - Preview", vista)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # === FRAUDE ===
            if not es_real and not es_dist:
                if ahora - t_evento >= COOLDOWN_EVENTO:
                    t_evento = ahora
                    ruta = _guardar_foto(color, "fraude")
                    cola_eventos.put({
                        "tipo": "FRAUDE",
                        "motivo": motivo,
                        "metricas": metricas,
                        "foto_ruta": ruta,
                        "frame": color.copy()
                    })
                nombre_actual = None
                # Preview fraude
                vista = _dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    None, 0, False
                )
                cv2.imshow("DepthGuard - Preview", vista)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # === DISTANCIA ===
            if es_dist:
                # Preview distancia
                vista = _dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    None, 0, False
                )
                cv2.imshow("DepthGuard - Preview", vista)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # === RECONOCIMIENTO (cada 2s) ===
            if ahora - t_embedding >= COOLDOWN_EMBEDDING:
                t_embedding = ahora

                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                if embedding is None:
                    continue

                nombre, confianza = reconocedor.buscar(embedding)
                nombre_actual = nombre
                confianza_actual = confianza

                if nombre:
                    if ahora - t_evento >= COOLDOWN_EVENTO:
                        t_evento = ahora
                        ruta = _guardar_foto(color, "acceso")
                        cola_eventos.put({
                            "tipo": "ACCESO_PERMITIDO",
                            "nombre": nombre,
                            "confianza": confianza,
                            "metricas": metricas,
                            "foto_ruta": ruta,
                            "frame": color.copy()
                        })
                else:
                    if ahora - t_evento >= COOLDOWN_EVENTO:
                        t_evento = ahora
                        ruta = _guardar_foto(color, "desconocido")
                        cola_eventos.put({
                            "tipo": "DESCONOCIDO",
                            "metricas": metricas,
                            "foto_ruta": ruta,
                            "frame": color.copy()
                        })

            # Preview reconocimiento
            vista = _dibujar_preview(
                color, bbox, es_real, es_dist, motivo, metricas,
                nombre_actual, confianza_actual, False
            )
            cv2.imshow("DepthGuard - Preview", vista)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # Recargar caché si se registró alguien nuevo
            if modo_registro.get("recargar_cache"):
                usuarios = db_manager.obtener_todos_usuarios()
                reconocedor.recargar_cache(usuarios)
                modo_registro["recargar_cache"] = False

    except Exception as e:
        print(f"❌ Error pipeline: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cv2.destroyAllWindows()
        detector.cerrar()
        camara.cerrar()
