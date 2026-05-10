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
import json

from motor_ia.camara.factory import crear_camara
from motor_ia.deteccion.face_mesh import DetectorFaceMesh
from motor_ia.antispoofing.verificador_3d import VerificadorAntiSpoofing
from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial
from motor_ia.visualizacion import dibujar_preview, mostrar_preview
from backend.supabase_cliente import obtener_cliente
from config.settings import (
    COOLDOWN_EMBEDDING, COOLDOWN_ANTISPOOFING,
    COOLDOWN_EVENTO, CAPTURAS_DIR
)

# FPS objetivo para el pipeline (evita consumir 100% CPU)
TARGET_FPS = 20
MIN_FRAME_TIME = 1.0 / TARGET_FPS


def _guardar_foto(imagen, prefijo):
    """Guarda captura y retorna ruta relativa."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{prefijo}_{timestamp}.jpg"
    ruta_completa = os.path.join(CAPTURAS_DIR, nombre)
    cv2.imwrite(ruta_completa, imagen, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return f"/capturas/{nombre}"


def _cargar_usuarios_supabase():
    """Carga usuarios desde Supabase y los formatea para el reconocedor."""
    try:
        supabase = obtener_cliente()
        resp = supabase.table("usuarios").select(
            "id, nombre, embeddings_json, num_angulos, activo"
        ).eq("activo", True).execute()

        usuarios = []
        for row in resp.data:
            emb = row.get("embeddings_json")
            if emb:
                usuarios.append({
                    "id": row["id"],
                    "nombre": row["nombre"],
                    "embeddings": emb if isinstance(emb, list) else json.loads(emb),
                    "num_angulos": row.get("num_angulos", 0),
                })
        return usuarios
    except Exception as e:
        print(f"⚠️ Error cargando usuarios de Supabase: {e}")
        return []


def ejecutar_pipeline(cola_eventos, modo_registro, db_manager=None):
    """
    Bucle principal. Corre en un hilo separado.
    modo_registro: instancia de EstadoRegistro (thread-safe).
    db_manager: legacy, ya no se usa (los usuarios se cargan de Supabase).
    """

    # Crear componentes
    camara = crear_camara()
    detector = DetectorFaceMesh()
    antispoofing = VerificadorAntiSpoofing()
    reconocedor = ReconocedorFacial()

    # Detectar si es cámara simulada para optimizar profundidad
    _es_simulada = hasattr(camara, 'actualizar_profundidad')

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

    # Cargar usuarios desde Supabase
    usuarios = _cargar_usuarios_supabase()
    reconocedor.cargar_cache(usuarios)
    print(f"   👥 {len(usuarios)} usuarios cargados desde Supabase")

    # Timers
    t_embedding = 0
    t_spoofing = 0
    t_evento = 0

    # Cache
    spoofing_cache = None

    # Estado para preview
    nombre_actual = None
    confianza_actual = 0

    # FPS counter para debug
    _fps_count = 0
    _fps_timer = time.time()

    print("🟢 Pipeline IA activo")
    print("   📺 Ventana de preview abierta (presiona 'q' para cerrar)")

    try:
        while True:
            frame_start = time.time()

            color, profundidad = camara.obtener_frames()

            if color is None:
                time.sleep(0.05)
                continue

            ahora = time.time()

            # Redimensionar si la cámara entregó un frame más grande que 640x480
            h_orig, w_orig = color.shape[:2]
            if w_orig > 640:
                scale = 640 / w_orig
                new_h = int(h_orig * scale)
                color = cv2.resize(color, (640, new_h), interpolation=cv2.INTER_AREA)
                if profundidad is not None:
                    profundidad = cv2.resize(profundidad, (640, new_h), interpolation=cv2.INTER_NEAREST)

            imagen_rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)

            # === DETECCIÓN (cada frame) ===
            encontrada, bbox, angulo, direccion = detector.detectar(imagen_rgb)

            if not encontrada:
                # Mostrar frame sin detección (reusar frame directamente)
                cv2.putText(color, "DEPTHGUARD - Preview", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(color, "Sin rostro detectado", (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
                if mostrar_preview(color):
                    break
                # Limitar FPS cuando no hay rostro (menos urgencia)
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME * 2)
                continue

            # Si cámara simulada: generar profundidad a partir del bbox ya detectado
            if _es_simulada and bbox is not None:
                camara.actualizar_profundidad(bbox)
                profundidad = camara._prof_cache if camara._prof_cache is not None else profundidad

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
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME)
                continue

            es_real, es_dist, motivo, metricas = spoofing_cache

            # === REGISTRO ===
            if modo_registro.activo and es_real:
                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                if embedding is not None:
                    # Acumular embedding real en el estado de registro
                    modo_registro.agregar_embedding(embedding)
                    paso = len(modo_registro.embeddings)
                    modo_registro.paso = paso
                    print(f"   📸 Registro: embedding {paso}/5 capturado (ángulo: {direccion})")
                # Preview en modo registro
                vista = dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    modo_registro.nombre, 0, True
                )
                if mostrar_preview(vista):
                    break
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME)
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
                    nombre, confianza, usuario_id = reconocedor.buscar(embedding)
                    nombre_actual = nombre
                    confianza_actual = confianza

                    if nombre:
                        if ahora - t_evento >= COOLDOWN_EVENTO:
                            t_evento = ahora
                            ruta = _guardar_foto(color, "acceso")
                            cola_eventos.put({
                                "tipo": "ACCESO_PERMITIDO",
                                "nombre": nombre,
                                "usuario_id": usuario_id,
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

            # Preview unificado (un solo punto de render, sin .copy())
            vista = dibujar_preview(
                color, bbox, es_real, es_dist, motivo, metricas,
                nombre_actual, confianza_actual, modo_registro.activo
            )
            if mostrar_preview(vista):
                break

            # Recargar caché si se registró alguien nuevo
            if modo_registro.recargar_cache:
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                modo_registro.recargar_cache = False
                print(f"   🔄 Caché recargada: {len(usuarios)} usuarios")

            # FPS debug (cada 3 segundos)
            _fps_count += 1
            if ahora - _fps_timer >= 3.0:
                fps = _fps_count / (ahora - _fps_timer)
                _fps_count = 0
                _fps_timer = ahora

            # Limitar FPS para no saturar CPU
            _dormir_hasta_fps(frame_start, MIN_FRAME_TIME)

    except Exception as e:
        print(f"❌ Error pipeline: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cv2.destroyAllWindows()
        detector.cerrar()
        camara.cerrar()


def _dormir_hasta_fps(frame_start, target_time):
    """Duerme lo necesario para no exceder el FPS objetivo."""
    elapsed = time.time() - frame_start
    if elapsed < target_time:
        time.sleep(target_time - elapsed)
