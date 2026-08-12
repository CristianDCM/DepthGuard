"""
Orquestador principal del Motor IA.
Cámara → Detección → Anti-spoofing → Reconocimiento
Envía resultados al Backend por queue.Queue

Soporta detección simultánea de hasta 5 personas,
cada una con su propio estado de sesión independiente.
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
from motor_ia.validacion_calidad import validar_calidad_rostro
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
CACHE_REFRESH_INTERVAL = 60

# Intervalo entre snapshots para preview en vivo (segundos)
SNAPSHOT_INTERVAL = 2.0

# Evento global para forzar recarga de caché desde otros hilos
cache_invalidada = threading.Event()

# Timeout para considerar que una persona se fue (segundos)
_SESION_TIMEOUT = 30


# ======================================================================
# PersonaTrack: estado independiente por cada persona detectada
# ======================================================================

class PersonaTrack:
    """Estado de seguimiento para una persona individual en el frame."""

    def __init__(self, bbox, angulo, direccion):
        # Posición actual
        self.bbox = bbox
        self.angulo = angulo
        self.direccion = direccion

        # Anti-spoofing
        self.spoofing_cache = None   # (es_real, es_dist, motivo, metricas)
        self.t_spoofing = 0

        # Reconocimiento
        self.nombre = None
        self.confianza = 0
        self.usuario_id = None
        self.t_embedding = 0

        # Sesión (evitar eventos repetidos)
        self.sesion_tipo = None      # "ACCESO_PERMITIDO", "DESCONOCIDO", "FRAUDE"
        self.sesion_sujeto = None

        # Tracking
        self.ultimo_visto = time.time()
        self.id = id(self)  # Identificador único del track

    def centroide(self):
        """Retorna (cx, cy) del centro del bbox."""
        x, y, x2, y2 = self.bbox
        return ((x + x2) / 2, (y + y2) / 2)

    def actualizar_posicion(self, bbox, angulo, direccion):
        """Actualiza la posición del track con la nueva detección."""
        self.bbox = bbox
        self.angulo = angulo
        self.direccion = direccion
        self.ultimo_visto = time.time()

    def esta_activo(self, ahora):
        """Retorna True si el track sigue activo (no ha expirado)."""
        return (ahora - self.ultimo_visto) < _SESION_TIMEOUT

    def to_vis_dict(self):
        """Convierte el track a dict para visualización."""
        es_real = True
        es_dist = False
        motivo = ""
        metricas = {}

        if self.spoofing_cache:
            es_real, es_dist, motivo, metricas = self.spoofing_cache

        return {
            "bbox": self.bbox,
            "es_real": es_real,
            "es_dist": es_dist,
            "motivo": motivo,
            "metricas": metricas,
            "nombre": self.nombre,
            "confianza": self.confianza,
        }


def _distancia_centroides(bbox_a, bbox_b):
    """Distancia euclidiana entre los centroides de dos bboxes."""
    cx_a = (bbox_a[0] + bbox_a[2]) / 2
    cy_a = (bbox_a[1] + bbox_a[3]) / 2
    cx_b = (bbox_b[0] + bbox_b[2]) / 2
    cy_b = (bbox_b[1] + bbox_b[3]) / 2
    return ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5


def _asociar_detecciones(tracks, detecciones, umbral=120):
    """
    Asocia detecciones nuevas con tracks existentes por distancia de centroide.
    
    Retorna lista de (track_o_None, bbox, angulo, direccion).
    track=None significa detección nueva (persona que acaba de aparecer).
    """
    if not tracks:
        # Sin tracks: todas son detecciones nuevas
        return [(None, bbox, ang, dir) for bbox, ang, dir in detecciones]

    usados = set()
    resultado = []

    for det in detecciones:
        bbox_det, angulo, direccion = det
        mejor_dist = umbral
        mejor_track = None

        for track in tracks:
            if track.id in usados:
                continue
            dist = _distancia_centroides(track.bbox, bbox_det)
            if dist < mejor_dist:
                mejor_dist = dist
                mejor_track = track

        if mejor_track is not None:
            usados.add(mejor_track.id)

        # track=None si no se encontró match (persona nueva)
        resultado.append((mejor_track, bbox_det, angulo, direccion))

    return resultado


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
        print(f" Error cargando usuarios de Supabase: {e}")
        return []


def ejecutar_pipeline(cola_eventos, modo_registro, db_manager=None, frame_provider=None):
    """
    Bucle principal. Corre en un hilo separado.
    modo_registro: instancia de EstadoRegistro (thread-safe).
    db_manager: legacy, ya no se usa (los usuarios se cargan de Supabase).
    frame_provider: instancia de FrameProvider (opcional).
    """

    # Crear componentes
    camara = crear_camara()
    detector = DetectorFaceMesh(max_rostros=5)
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
            print(f" Cámara: {e}. Reintento en {espera}s...")
            time.sleep(espera)

    # Cargar usuarios desde Supabase
    usuarios = _cargar_usuarios_supabase()
    reconocedor.cargar_cache(usuarios)
    print(f"    {len(usuarios)} usuarios cargados desde Supabase")

    # Timers globales
    t_cache_refresh = time.time()
    t_snapshot = 0

    # Tracks activos (lista de PersonaTrack)
    tracks_activos = []

    # Estado de estabilización para registro (1 persona a la vez)
    _reg_dir_actual = None
    _reg_tiempo_inicio = 0
    _reg_captura_flash = 0

    # FPS counter para debug
    _fps_count = 0
    _fps_timer = time.time()

    print(" Pipeline IA activo (multi-rostro, máx 5)")
    print("    Ventana de preview abierta (presiona 'q' para cerrar)")

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

            # === DETECCIÓN (cada frame) — retorna lista de rostros ===
            detecciones = detector.detectar(imagen_rgb)

            # Limpiar tracks expirados
            tracks_activos = [t for t in tracks_activos if t.esta_activo(ahora)]

            if not detecciones:
                # Sin rostros: resetear estabilización de registro
                _reg_dir_actual = None
                _reg_tiempo_inicio = 0

                cv2.putText(color, "DEPTHGUARD - Preview", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                msg_sin_rostro = "Sin rostro detectado"
                if modo_registro.activo:
                    msg_sin_rostro = "Coloque su rostro frente a la camara"
                cv2.putText(color, msg_sin_rostro, (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
                if mostrar_preview(color):
                    break
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME * 2)
                continue

            # === ASOCIAR detecciones con tracks existentes ===
            matched = _asociar_detecciones(tracks_activos, detecciones)

            tracks_frame = []  # Tracks para este frame

            for match in matched:
                track_existente, bbox, angulo, direccion = match

                if track_existente is not None:
                    # Track existente: actualizar posición
                    track_existente.actualizar_posicion(bbox, angulo, direccion)
                    track = track_existente
                else:
                    # Nuevo track
                    track = PersonaTrack(bbox, angulo, direccion)
                    tracks_activos.append(track)

                # Si cámara simulada: generar profundidad a partir del bbox
                if _es_simulada and bbox is not None:
                    camara.actualizar_profundidad(bbox)
                    profundidad = camara._prof_cache if camara._prof_cache is not None else profundidad

                # === MODO REGISTRO (solo la persona más grande/cercana) ===
                if modo_registro.activo:
                    # Solo procesar la persona con el bbox más grande (más cercana)
                    if track == _persona_mas_grande(tracks_activos):
                        es_real_reg = True
                        if track.spoofing_cache:
                            es_real_reg = track.spoofing_cache[0]

                        # Anti-spoofing para registro
                        if ahora - track.t_spoofing >= COOLDOWN_ANTISPOOFING:
                            track.t_spoofing = ahora
                            es_real, es_dist, motivo, metricas = antispoofing.verificar(
                                profundidad, bbox
                            )
                            metricas["angulo"] = angulo
                            metricas["direccion"] = direccion
                            track.spoofing_cache = (es_real, es_dist, motivo, metricas)
                            es_real_reg = es_real

                        if es_real_reg:
                            _procesar_registro(
                                track, modo_registro, reconocedor, imagen_rgb,
                                ahora, _reg_dir_actual, _reg_tiempo_inicio,
                                _reg_captura_flash
                            )
                            # Actualizar estado de estabilización
                            angulo_solicitado = modo_registro.angulo_solicitado
                            angulo_ok = (direccion == angulo_solicitado)
                            if angulo_ok:
                                if _reg_dir_actual != angulo_solicitado:
                                    _reg_dir_actual = angulo_solicitado
                                    _reg_tiempo_inicio = ahora
                            else:
                                _reg_dir_actual = None
                                _reg_tiempo_inicio = 0

                            # Verificar captura
                            tiempo_estable = ahora - _reg_tiempo_inicio if _reg_dir_actual else 0
                            if angulo_ok and tiempo_estable >= TIEMPO_ESTABILIZACION and modo_registro.puede_capturar():
                                # === VALIDACIÓN DE CALIDAD ===
                                calidad_ok, motivo_calidad = validar_calidad_rostro(imagen_rgb, bbox)
                                if not calidad_ok:
                                    # Calidad insuficiente: mostrar advertencia pero no capturar
                                    track_dict = track.to_vis_dict()
                                    track_dict["registro_info"] = {
                                        "angulo_solicitado": angulo_solicitado,
                                        "paso": modo_registro.paso,
                                        "angulo_ok": True,
                                        "estabilizado": True,
                                        "tiempo_estable": tiempo_estable,
                                        "captura_reciente": False,
                                        "angulos_capturados": modo_registro.angulos_capturados,
                                        "nombre": modo_registro.nombre,
                                        "calidad_error": motivo_calidad,
                                    }
                                    tracks_frame.append(track_dict)
                                    continue

                                embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                                if embedding is not None:
                                    modo_registro.registrar_captura(embedding, angulo_solicitado)
                                    _reg_captura_flash = ahora
                                    _reg_dir_actual = None
                                    _reg_tiempo_inicio = 0
                                    print(f"    Registro: embedding {modo_registro.paso}/5 capturado (ángulo: {angulo_solicitado}) | {motivo_calidad}")

                            captura_reciente = (ahora - _reg_captura_flash) < 0.8
                            track_dict = track.to_vis_dict()
                            track_dict["registro_info"] = {
                                "angulo_solicitado": angulo_solicitado,
                                "paso": modo_registro.paso,
                                "angulo_ok": angulo_ok,
                                "estabilizado": angulo_ok and tiempo_estable >= TIEMPO_ESTABILIZACION * 0.5,
                                "tiempo_estable": tiempo_estable,
                                "captura_reciente": captura_reciente,
                                "angulos_capturados": modo_registro.angulos_capturados,
                                "nombre": modo_registro.nombre,
                            }
                            tracks_frame.append(track_dict)
                        else:
                            tracks_frame.append(track.to_vis_dict())
                    else:
                        # Otras personas durante registro: mostrar bbox gris
                        tracks_frame.append(track.to_vis_dict())
                    continue

                # === MODO NORMAL: Anti-spoofing + Reconocimiento por persona ===

                # Anti-spoofing (cada COOLDOWN_ANTISPOOFING por persona)
                if ahora - track.t_spoofing >= COOLDOWN_ANTISPOOFING:
                    track.t_spoofing = ahora
                    es_real, es_dist, motivo, metricas = antispoofing.verificar(
                        profundidad, bbox
                    )
                    metricas["angulo"] = angulo
                    metricas["direccion"] = direccion
                    track.spoofing_cache = (es_real, es_dist, motivo, metricas)

                if track.spoofing_cache is None:
                    tracks_frame.append(track.to_vis_dict())
                    continue

                es_real, es_dist, motivo, metricas = track.spoofing_cache

                # === FRAUDE ===
                if not es_real and not es_dist:
                    if track.sesion_tipo != "FRAUDE":
                        track.sesion_tipo = "FRAUDE"
                        track.sesion_sujeto = None
                        track.usuario_id = None
                        ruta = _guardar_foto(color, "fraude")
                        cola_eventos.put({
                            "tipo": "FRAUDE",
                            "motivo": motivo,
                            "metricas": metricas,
                            "foto_ruta": ruta,
                            "frame": color.copy()
                        })

                # === DISTANCIA ===
                elif es_dist:
                    pass  # Solo se muestra en preview

                # === RECONOCIMIENTO (cada COOLDOWN_EMBEDDING por persona) ===
                elif ahora - track.t_embedding >= COOLDOWN_EMBEDDING:
                    track.t_embedding = ahora

                    embedding = reconocedor.generar_embedding(imagen_rgb, bbox)
                    if embedding is not None:
                        nombre, confianza, usuario_id = reconocedor.buscar(embedding)
                        track.nombre = nombre
                        track.confianza = confianza
                        track.usuario_id = usuario_id

                        if nombre:
                            es_nuevo = (
                                track.sesion_tipo != "ACCESO_PERMITIDO" or
                                track.sesion_sujeto != nombre
                            )
                            if es_nuevo:
                                track.sesion_tipo = "ACCESO_PERMITIDO"
                                track.sesion_sujeto = nombre
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
                            if track.sesion_tipo != "DESCONOCIDO":
                                track.sesion_tipo = "DESCONOCIDO"
                                track.sesion_sujeto = None
                                track.usuario_id = None
                                ruta = _guardar_foto(color, "desconocido")
                                cola_eventos.put({
                                    "tipo": "DESCONOCIDO",
                                    "metricas": metricas,
                                    "foto_ruta": ruta,
                                    "frame": color.copy()
                                })

                tracks_frame.append(track.to_vis_dict())

            # === VISUALIZACIÓN ===
            registro_info_global = None
            if modo_registro.activo:
                registro_info_global = {
                    "angulo_solicitado": modo_registro.angulo_solicitado,
                    "paso": modo_registro.paso,
                    "angulos_capturados": modo_registro.angulos_capturados,
                    "nombre": modo_registro.nombre,
                    "angulo_ok": _reg_dir_actual is not None,
                    "captura_reciente": (ahora - _reg_captura_flash) < 0.8,
                }

            vista = dibujar_preview(
                color, tracks_frame, modo_registro.activo,
                registro_info=registro_info_global
            )
            if mostrar_preview(vista):
                break

            # === WEBRTC: actualizar FrameProvider ===
            if frame_provider is not None:
                frame_provider.update_frame(vista.copy())

            # === SNAPSHOT para preview en vivo (cada 2s) ===
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
                t_cache_refresh = ahora
                # Forzar re-reconocimiento sin destruir la sesión
                # (evita generar eventos duplicados para personas que siguen presentes)
                for t in tracks_activos:
                    t.t_embedding = 0  # Forzar re-evaluación inmediata
                    t.nombre = None
                    t.confianza = 0
                print(f"    Caché recargada (registro): {len(usuarios)} usuarios")

            # Recargar caché si fue invalidada externamente
            if cache_invalidada.is_set():
                cache_invalidada.clear()
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                t_cache_refresh = ahora
                for t in tracks_activos:
                    t.t_embedding = 0
                    t.nombre = None
                    t.confianza = 0
                print(f"    Caché recargada (invalidación externa): {len(usuarios)} usuarios")

            # Recarga periódica automática cada 60s
            if ahora - t_cache_refresh >= CACHE_REFRESH_INTERVAL:
                t_cache_refresh = ahora
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                for t in tracks_activos:
                    t.t_embedding = 0
                    t.nombre = None
                    t.confianza = 0

            # FPS debug (cada 3 segundos)
            _fps_count += 1
            if ahora - _fps_timer >= 3.0:
                fps = _fps_count / (ahora - _fps_timer)
                _fps_count = 0
                _fps_timer = ahora

            # Limitar FPS para no saturar CPU
            _dormir_hasta_fps(frame_start, MIN_FRAME_TIME)

    except Exception as e:
        print(f" Error pipeline: {e}")
        import traceback
        traceback.print_exc()

    finally:
        cv2.destroyAllWindows()
        detector.cerrar()
        camara.cerrar()


def _persona_mas_grande(tracks):
    """Retorna el track con el bbox más grande (persona más cercana)."""
    if not tracks:
        return None
    return max(tracks, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))


def _procesar_registro(track, modo_registro, reconocedor, imagen_rgb, ahora,
                        reg_dir, reg_tiempo, reg_flash):
    """Helper para procesamiento de registro (placeholder para lógica inline)."""
    pass  # La lógica se maneja inline en el bucle principal


def _dormir_hasta_fps(frame_start, target_time):
    """Duerme lo necesario para no exceder el FPS objetivo."""
    elapsed = time.time() - frame_start
    if elapsed < target_time:
        time.sleep(target_time - elapsed)
