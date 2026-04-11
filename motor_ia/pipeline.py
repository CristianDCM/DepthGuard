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
from motor_ia.visualizacion import dibujar_preview, mostrar_preview
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


def ejecutar_pipeline(cola_eventos, modo_registro, db_manager):
    """
    Bucle principal. Corre en un hilo separado.
    modo_registro: instancia de EstadoRegistro (thread-safe).
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
                if mostrar_preview(vista):
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
                vista = dibujar_preview(
                    color, bbox, True, False, "Analizando...", {},
                    None, 0, modo_registro.activo
                )
                if mostrar_preview(vista):
                    break
                continue

            es_real, es_dist, motivo, metricas = spoofing_cache

            # === REGISTRO ===
            if modo_registro.activo and es_real:
                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                if embedding is not None:
                    cola_eventos.put({
                        "tipo": "REGISTRO_EMBEDDING",
                        "embedding": embedding,
                        "angulo": angulo,
                        "frame": color.copy()
                    })
                # Preview en modo registro
                vista = dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    None, 0, True
                )
                if mostrar_preview(vista):
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

            # === DISTANCIA ===
            elif es_dist:
                pass  # Solo se muestra en preview

            # === RECONOCIMIENTO (cada 2s) ===
            elif ahora - t_embedding >= COOLDOWN_EMBEDDING:
                t_embedding = ahora

                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                if embedding is not None:
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

            # Preview unificado (un solo punto de render)
            vista = dibujar_preview(
                color, bbox, es_real, es_dist, motivo, metricas,
                nombre_actual, confianza_actual, modo_registro.activo
            )
            if mostrar_preview(vista):
                break

            # Recargar caché si se registró alguien nuevo
            if modo_registro.recargar_cache:
                usuarios = db_manager.obtener_todos_usuarios()
                reconocedor.recargar_cache(usuarios)
                modo_registro.recargar_cache = False

    except Exception as e:
        print(f"❌ Error pipeline: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cv2.destroyAllWindows()
        detector.cerrar()
        camara.cerrar()
