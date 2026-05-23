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
import threading

from motor_ia.camara.factory import crear_camara
from motor_ia.deteccion.face_mesh import DetectorFaceMesh
from motor_ia.antispoofing.verificador_3d import VerificadorAntiSpoofing
from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial
from motor_ia.visualizacion import dibujar_preview, mostrar_preview
from motor_ia.estado_registro import ANGULOS_REGISTRO
from backend.supabase_cliente import obtener_cliente
from backend.snapshot_uploader import subir_snapshot
from config.settings import (
    COOLDOWN_EMBEDDING, COOLDOWN_ANTISPOOFING,
    CAPTURAS_DIR
)

# FPS objetivo para el pipeline (evita consumir 100% CPU)
TARGET_FPS = 20
MIN_FRAME_TIME = 1.0 / TARGET_FPS

# Tiempo que la persona debe mantener la pose antes de capturar (segundos)
TIEMPO_ESTABILIZACION = 1.0

# Intervalo de recarga automática de caché (segundos)
# Detecta eliminaciones de usuarios hechas desde el frontend
CACHE_REFRESH_INTERVAL = 60

# Intervalo entre snapshots para preview en vivo (segundos)
SNAPSHOT_INTERVAL = 2.0

# Evento global para forzar recarga de caché desde otros hilos (ej: sync)
cache_invalidada = threading.Event()


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


def ejecutar_pipeline(cola_eventos, modo_registro, db_manager=None, frame_provider=None):
    """
    Bucle principal. Corre en un hilo separado.
    modo_registro: instancia de EstadoRegistro (thread-safe).
    db_manager: legacy, ya no se usa (los usuarios se cargan de Supabase).
    frame_provider: instancia de FrameProvider (opcional). Si se pasa,
        el último frame renderizado se entrega al servidor WebRTC vía
        un buffer thread-safe. El pipeline NO usa asyncio en ningún momento.
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
    t_cache_refresh = time.time()  # Para recarga periódica de caché
    t_snapshot = 0                 # Para snapshots de preview en vivo

    # Cache
    spoofing_cache = None

    # Estado para preview
    nombre_actual = None
    confianza_actual = 0

    # Estado de estabilización para registro
    _reg_dir_actual = None       # Última dirección detectada durante registro
    _reg_tiempo_inicio = 0       # Cuándo empezó a mirar en la dirección correcta
    _reg_captura_flash = 0       # Timestamp del flash verde de captura exitosa

    # FPS counter para debug
    _fps_count = 0
    _fps_timer = time.time()

    # === Tracking de sesión de presencia ===
    # Evita emitir eventos repetidos para la misma persona parada frente a la cámara.
    # Solo emite un nuevo evento cuando:
    #   1. Cambia el sujeto (persona diferente)
    #   2. Cambia el estado (de ACCESO a FRAUDE, etc.)
    #   3. El rostro desaparece por >30s y vuelve
    _sesion_tipo = None          # "ACCESO_PERMITIDO", "DESCONOCIDO", "FRAUDE" o None
    _sesion_sujeto = None        # nombre del sujeto actual (None = desconocido)
    _sesion_usuario_id = None    # ID del usuario de la sesión actual
    _ultimo_rostro_visto = 0     # Timestamp de la última vez que se vio un rostro
    _SESION_TIMEOUT = 30         # Segundos sin rostro para considerar que la persona se fue

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
                # Resetear estabilización si se pierde el rostro
                _reg_dir_actual = None
                _reg_tiempo_inicio = 0

                # Si el rostro desapareció por más del timeout, resetear sesión
                if _sesion_tipo is not None and (ahora - _ultimo_rostro_visto) >= _SESION_TIMEOUT:
                    _sesion_tipo = None
                    _sesion_sujeto = None
                    _sesion_usuario_id = None

                # Mostrar frame sin detección (reusar frame directamente)
                cv2.putText(color, "DEPTHGUARD - Preview", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                msg_sin_rostro = "Sin rostro detectado"
                if modo_registro.activo:
                    msg_sin_rostro = "Coloque su rostro frente a la camara"
                cv2.putText(color, msg_sin_rostro, (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
                if mostrar_preview(color):
                    break
                # Limitar FPS cuando no hay rostro (menos urgencia)
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME * 2)
                continue

            # Marcar que estamos viendo un rostro ahora
            _ultimo_rostro_visto = ahora

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

            # === REGISTRO CON GUIADO DE ÁNGULOS ===
            if modo_registro.activo and es_real:
                angulo_solicitado = modo_registro.angulo_solicitado
                angulo_ok = (direccion == angulo_solicitado)
                captura_reciente = (ahora - _reg_captura_flash) < 0.8  # flash 0.8s

                # Lógica de estabilización
                if angulo_ok:
                    if _reg_dir_actual != angulo_solicitado:
                        # Acaba de girar a la dirección correcta
                        _reg_dir_actual = angulo_solicitado
                        _reg_tiempo_inicio = ahora
                    
                    tiempo_estable = ahora - _reg_tiempo_inicio

                    # Capturar cuando está estable el tiempo suficiente
                    if tiempo_estable >= TIEMPO_ESTABILIZACION and modo_registro.puede_capturar():
                        embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                        if embedding is not None:
                            modo_registro.registrar_captura(embedding, angulo_solicitado)
                            paso = modo_registro.paso
                            _reg_captura_flash = ahora
                            _reg_dir_actual = None  # Reset para siguiente ángulo
                            _reg_tiempo_inicio = 0
                            print(f"   📸 Registro: embedding {paso}/5 capturado (ángulo: {angulo_solicitado})")
                else:
                    # No está mirando en la dirección correcta
                    _reg_dir_actual = None
                    _reg_tiempo_inicio = 0
                    tiempo_estable = 0

                # Info para visualización
                registro_info = {
                    "angulo_solicitado": angulo_solicitado,
                    "paso": modo_registro.paso,
                    "angulo_ok": angulo_ok,
                    "estabilizado": angulo_ok and (ahora - _reg_tiempo_inicio) >= TIEMPO_ESTABILIZACION * 0.5,
                    "tiempo_estable": (ahora - _reg_tiempo_inicio) if angulo_ok and _reg_tiempo_inicio > 0 else 0,
                    "captura_reciente": captura_reciente,
                    "angulos_capturados": modo_registro.angulos_capturados,
                    "nombre": modo_registro.nombre,
                }

                vista = dibujar_preview(
                    color, bbox, es_real, es_dist, motivo, metricas,
                    modo_registro.nombre, 0, True,
                    registro_info=registro_info
                )
                if mostrar_preview(vista):
                    break
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME)
                continue

            # === FRAUDE ===
            if not es_real and not es_dist:
                # Solo emitir si es una situación nueva (no estaba en FRAUDE)
                if _sesion_tipo != "FRAUDE":
                    _sesion_tipo = "FRAUDE"
                    _sesion_sujeto = None
                    _sesion_usuario_id = None
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
                        # Solo emitir evento si es un sujeto diferente
                        # o la sesión había expirado
                        es_nuevo = (
                            _sesion_tipo != "ACCESO_PERMITIDO" or
                            _sesion_sujeto != nombre
                        )
                        if es_nuevo:
                            _sesion_tipo = "ACCESO_PERMITIDO"
                            _sesion_sujeto = nombre
                            _sesion_usuario_id = usuario_id
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
                        # Solo emitir DESCONOCIDO una vez por sesión
                        if _sesion_tipo != "DESCONOCIDO":
                            _sesion_tipo = "DESCONOCIDO"
                            _sesion_sujeto = None
                            _sesion_usuario_id = None
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

            # === WEBRTC: actualizar FrameProvider (cada frame) ===
            # Llamada síncrona y thread-safe. No bloquea el pipeline.
            if frame_provider is not None:
                frame_provider.update_frame(vista.copy())

            # === SNAPSHOT para preview en vivo (cada 2s) ===
            # snapshot_uploader.py se conserva intacto como fallback.
            if ahora - t_snapshot >= SNAPSHOT_INTERVAL:
                t_snapshot = ahora
                threading.Thread(
                    target=subir_snapshot,
                    args=(vista.copy(),),
                    daemon=True
                ).start()

            # Recargar caché si se registró alguien nuevo
            if modo_registro.recargar_cache:
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                modo_registro.recargar_cache = False
                t_cache_refresh = ahora  # Reset timer
                print(f"   🔄 Caché recargada (registro): {len(usuarios)} usuarios")

            # Recargar caché si fue invalidada externamente (ej: FK error en sync)
            if cache_invalidada.is_set():
                cache_invalidada.clear()
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                t_cache_refresh = ahora
                nombre_actual = None
                confianza_actual = 0
                # Resetear sesión para re-evaluar el rostro actual
                _sesion_tipo = None
                _sesion_sujeto = None
                _sesion_usuario_id = None
                print(f"   🔄 Caché recargada (invalidación externa): {len(usuarios)} usuarios")

            # Recarga periódica automática cada 60s
            # Detecta eliminaciones de usuarios desde el frontend
            if ahora - t_cache_refresh >= CACHE_REFRESH_INTERVAL:
                t_cache_refresh = ahora
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                nombre_actual = None
                confianza_actual = 0
                # Resetear sesión para re-evaluar
                _sesion_tipo = None
                _sesion_sujeto = None
                _sesion_usuario_id = None

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
