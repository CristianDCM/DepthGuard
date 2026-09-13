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
from motor_ia.tracking import (
    PersonaTrack, asociar_detecciones, escalar_bbox, persona_mas_grande,
    prioridad_reconocimiento,
)
from motor_ia.antispoofing.verificador_3d import VerificadorAntiSpoofing
from motor_ia.antispoofing.liveness import VerificadorLiveness, VIVO, FALLO
from motor_ia.reconocimiento.embedding_generator import ReconocedorFacial
from motor_ia.visualizacion import dibujar_preview, mostrar_preview
from motor_ia.validacion_calidad import (
    validar_calidad_rostro, apta_para_reconocimiento,
    pose_apta_para_reconocimiento,
)
from backend.supabase_cliente import obtener_cliente
from backend.snapshot_uploader import subir_snapshot
from config.settings import (
    COOLDOWN_EMBEDDING, COOLDOWN_EMBEDDING_VOTACION, COOLDOWN_ANTISPOOFING,
    CAPTURAS_DIR,
    MAX_YAW_RECONOCIMIENTO, MAX_PITCH_RECONOCIMIENTO,
    MAX_EMBEDDINGS_POR_FRAME,
    JITTERS_REGISTRO,
    REQUERIR_CAMARA_3D,
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

# Ancho al que se reduce el frame para detectar. El embedding NO usa este
# frame: se recorta del original a resolucion nativa (ver escalar_bbox).
ANCHO_DETECCION = 640

# Cuando un frame no pasa los gates de pose/calidad no se gasta el cooldown
# completo: se reintenta pronto, porque la persona puede corregir la pose
# en unas decimas de segundo.
REINTENTO_GATE = 0.3


def _preparar_crop(imagen_rgb, bbox, color_full, escala_full, rgb_full,
                   puntos=None):
    """
    Elige de qué imagen recortar el rostro para el embedding.

    Retorna (imagen, bbox, rgb_full, puntos). `rgb_full` es una caché por
    frame: convertir el frame nativo a RGB solo merece la pena si de verdad se
    va a generar un embedding, y solo una vez aunque haya varias personas.

    `puntos` se reproyecta junto con el bbox. El motor ONNX alinea el rostro a
    partir de 5 landmarks, y los landmarks vienen en coordenadas del frame
    REDUCIDO: usarlos sin escalar contra el frame nativo alinearía sobre la
    esquina superior izquierda de la imagen en vez de sobre la cara.
    """
    if escala_full <= 1.0:
        return imagen_rgb, bbox, rgb_full, puntos

    if rgb_full is None:
        rgb_full = cv2.cvtColor(color_full, cv2.COLOR_BGR2RGB)

    alto_f, ancho_f = rgb_full.shape[:2]
    puntos_full = None if puntos is None else puntos * escala_full
    return (rgb_full, escalar_bbox(bbox, escala_full, ancho_f, alto_f),
            rgb_full, puntos_full)


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
    detector = DetectorFaceMesh(max_rostros=5, confianza=0.5)
    antispoofing = VerificadorAntiSpoofing()
    liveness = VerificadorLiveness()
    reconocedor = ReconocedorFacial()

    # ¿La cámara MIDE profundidad, o no la tiene?
    # Solo el 3D de un sensor real es prueba de vida; la profundidad
    # sintética que antes generaba la cámara simulada se derivaba del propio
    # bbox detectado, asi que validaba una cúpula dibujada por el sistema.
    _hay_3d = getattr(camara, "profundidad_real", False)

    if not _hay_3d:
        if REQUERIR_CAMARA_3D:
            print(" REQUERIR_CAMARA_3D=true pero la cámara no entrega")
            print("    profundidad real. No se concederán accesos.")
        else:
            print(" AVISO DE SEGURIDAD: cámara sin profundidad real.")
            print("    Anti-spoofing 3D NO disponible.")
            print("    Los accesos se conceden solo con liveness 2D (parpadeo),")
            print("    que NO detiene un vídeo en bucle de la persona.")
            print("    En despliegue real usa REALSENSE y REQUERIR_CAMARA_3D=true.")

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

            # Reducir a ANCHO_DETECCION para detectar/visualizar, pero
            # CONSERVAR el frame original: el embedding se recorta de ahí.
            h_orig, w_orig = color.shape[:2]
            color_full = color
            escala_full = 1.0
            if w_orig > ANCHO_DETECCION:
                scale = ANCHO_DETECCION / w_orig
                new_h = int(h_orig * scale)
                color = cv2.resize(color, (ANCHO_DETECCION, new_h),
                                   interpolation=cv2.INTER_AREA)
                escala_full = w_orig / float(ANCHO_DETECCION)
                if profundidad is not None:
                    profundidad = cv2.resize(profundidad, (ANCHO_DETECCION, new_h),
                                             interpolation=cv2.INTER_NEAREST)

            imagen_rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)

            # Conversión del frame full-res: cara (a resolución nativa), así
            # que se hace una sola vez por frame y solo si algún rostro
            # llega realmente a generar un embedding.
            rgb_full = None

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

                # WebRTC: seguir transmitiendo aunque no haya rostros
                if frame_provider is not None:
                    frame_provider.update_frame(color.copy())

                if mostrar_preview(color):
                    break
                _dormir_hasta_fps(frame_start, MIN_FRAME_TIME * 2)
                continue

            # === ASOCIAR detecciones con tracks existentes ===
            matched = asociar_detecciones(tracks_activos, detecciones)

            # Reparto del presupuesto de embeddings del frame: primero quien
            # falta por identificar, y el más cercano de ellos.
            matched.sort(key=prioridad_reconocimiento)
            embeddings_restantes = MAX_EMBEDDINGS_POR_FRAME

            tracks_frame = []  # Tracks para este frame

            for track_existente, rostro in matched:
                bbox = rostro.bbox
                angulo = rostro.angulo_h
                angulo_v = rostro.angulo_v
                direccion = rostro.direccion

                if track_existente is not None:
                    # Track existente: actualizar posición
                    track_existente.actualizar_posicion(bbox, angulo, direccion, angulo_v)
                    track = track_existente
                else:
                    # Nuevo track
                    track = PersonaTrack(bbox, angulo, direccion, angulo_v)
                    tracks_activos.append(track)

                # === MODO REGISTRO (solo la persona más grande/cercana) ===
                if modo_registro.activo:
                    # Solo procesar la persona con el bbox más grande (más cercana)
                    if track == persona_mas_grande(tracks_activos):
                        es_real_reg = True
                        if _hay_3d and track.spoofing_cache:
                            es_real_reg = track.spoofing_cache[0]

                        # Anti-spoofing 3D para registro (solo con sensor real)
                        if _hay_3d and ahora - track.t_spoofing >= COOLDOWN_ANTISPOOFING:
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

                                # La plantilla de referencia se genera del
                                # frame nativo y con mas jitters: ocurre una
                                # sola vez por angulo, asi que la calidad
                                # importa mas que el coste.
                                img_emb, bbox_emb, rgb_full, puntos_emb = _preparar_crop(
                                    imagen_rgb, bbox, color_full, escala_full,
                                    rgb_full, rostro.puntos
                                )
                                embedding = reconocedor.generar_embedding(
                                    img_emb, bbox_emb,
                                    num_jitters=JITTERS_REGISTRO,
                                    puntos=puntos_emb
                                )
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

                # === MODO NORMAL: liveness + anti-spoofing 3D + reconocimiento ===

                # --- PRUEBA DE VIDA 2D (cada frame) ---
                # Se evalúa siempre, también con cámara 3D: defensa en capas.
                # Es por frame porque el parpadeo es una señal temporal.
                estado_liveness, motivo_liveness, met_liveness = liveness.evaluar(
                    track.parpadeo, rostro.puntos, imagen_rgb, bbox,
                    track.tiempo_visible(ahora)
                )
                track.liveness_estado = estado_liveness
                track.liveness_motivo = motivo_liveness
                track.liveness_metricas = met_liveness

                # --- ANTI-SPOOFING 3D (solo si la cámara MIDE profundidad) ---
                if _hay_3d and ahora - track.t_spoofing >= COOLDOWN_ANTISPOOFING:
                    track.t_spoofing = ahora
                    es_real, es_dist, motivo, metricas = antispoofing.verificar(
                        profundidad, bbox
                    )
                    metricas["angulo"] = angulo
                    metricas["direccion"] = direccion
                    track.spoofing_cache = (es_real, es_dist, motivo, metricas)

                if _hay_3d:
                    if track.spoofing_cache is None:
                        tracks_frame.append(track.to_vis_dict())
                        continue
                    es_real, es_dist, motivo, metricas = track.spoofing_cache
                else:
                    # Sin sensor no se inventan métricas 3D: antes se enviaban
                    # a Supabase valores fabricados (distancia 68.8cm siempre)
                    # que el operador leía como una medición real.
                    es_real, es_dist, motivo = True, False, ""
                    metricas = {"angulo": angulo, "direccion": direccion}

                # El evento queda trazable: qué capas verificaron de verdad.
                metricas["liveness"] = met_liveness
                metricas["verificacion"] = "3D+2D" if _hay_3d else "2D"

                # === FRAUDE: lo descarta el 3D, o lo descarta el liveness ===
                fraude_3d = (not es_real and not es_dist)
                fraude_liveness = (estado_liveness == FALLO)

                if fraude_3d or fraude_liveness:
                    if track.sesion_tipo != "FRAUDE":
                        track.sesion_tipo = "FRAUDE"
                        track.sesion_sujeto = None
                        track.usuario_id = None
                        ruta = _guardar_foto(color, "fraude")
                        cola_eventos.put({
                            "tipo": "FRAUDE",
                            "motivo": motivo if fraude_3d else motivo_liveness,
                            "metricas": metricas,
                            "foto_ruta": ruta,
                            "frame": color.copy()
                        })

                # === DISTANCIA ===
                elif es_dist:
                    pass  # Solo se muestra en preview

                # === RECONOCIMIENTO (con gates + votacion temporal) ===
                elif ahora >= track.t_proximo_embedding and embeddings_restantes > 0:

                    # --- Gate de pose ---
                    # Un rostro muy girado produce un embedding que no se
                    # parece a ninguna plantilla o, peor, se parece a la de
                    # otra persona. Mejor no opinar que opinar mal.
                    pose_ok, motivo_pose = pose_apta_para_reconocimiento(
                        angulo, angulo_v,
                        MAX_YAW_RECONOCIMIENTO, MAX_PITCH_RECONOCIMIENTO
                    )

                    # --- Gate de calidad ---
                    # Se evalua sobre el frame REDUCIDO a proposito: asi los
                    # umbrales en pixeles significan lo mismo con cualquier
                    # camara, independientemente de su resolucion nativa.
                    calidad_ok, motivo_calidad = True, ""
                    if pose_ok:
                        calidad_ok, motivo_calidad = apta_para_reconocimiento(
                            imagen_rgb, bbox
                        )

                    if not (pose_ok and calidad_ok):
                        # Frame no apto: no se vota (no contamina la ventana)
                        # y se reintenta enseguida, no al cabo del cooldown.
                        track.motivo_gate = motivo_pose or motivo_calidad
                        track.t_proximo_embedding = ahora + REINTENTO_GATE
                    else:
                        track.motivo_gate = ""

                        img_emb, bbox_emb, rgb_full, puntos_emb = _preparar_crop(
                            imagen_rgb, bbox, color_full, escala_full, rgb_full,
                            rostro.puntos
                        )
                        embeddings_restantes -= 1
                        embedding = reconocedor.generar_embedding(
                            img_emb, bbox_emb, puntos=puntos_emb
                        )

                        if embedding is not None:
                            nombre, confianza, usuario_id = reconocedor.buscar(
                                embedding, pose=direccion
                            )

                            # Un solo embedding no decide: vota.
                            # Decidir la identidad y CONCEDER el acceso son
                            # dos cosas distintas: lo segundo se hace abajo,
                            # y solo con prueba de vida.
                            track.registrar_voto(usuario_id, nombre, confianza)
                            hay, uid_v, nombre_v, conf_v = track.veredicto()
                            if hay:
                                track.nombre = nombre_v
                                track.confianza = conf_v
                                track.usuario_id = uid_v

                        # Cadencia rapida hasta tener veredicto, lenta despues:
                        # decidir rapido cuesta CPU, re-confirmar no hace falta
                        # que sea frecuente.
                        ya_decidido = track.sesion_tipo in ("ACCESO_PERMITIDO", "DESCONOCIDO")
                        track.t_proximo_embedding = ahora + (
                            COOLDOWN_EMBEDDING if ya_decidido
                            else COOLDOWN_EMBEDDING_VOTACION
                        )

                # === CONCESION DEL ACCESO ===
                # Se comprueba cada frame, no solo al cerrarse la votacion:
                # la identidad puede quedar decidida antes de que la persona
                # parpadee, y el acceso debe salir cuando llegan LAS DOS cosas.
                #
                # Sin prueba de vida no se concede nada. PENDIENTE no es
                # fraude: es "todavia no se sabe".
                if not fraude_3d and not fraude_liveness and not es_dist:
                    hay, uid_v, nombre_v, conf_v = track.veredicto()
                    vida_ok = (estado_liveness == VIVO)
                    # Si se exige sensor 3D, una camara sin el no concede nunca
                    hardware_ok = _hay_3d or not REQUERIR_CAMARA_3D

                    if hay and vida_ok and hardware_ok:
                        if nombre_v:
                            es_nuevo = (
                                track.sesion_tipo != "ACCESO_PERMITIDO" or
                                track.sesion_sujeto != uid_v
                            )
                            if es_nuevo:
                                track.sesion_tipo = "ACCESO_PERMITIDO"
                                track.sesion_sujeto = uid_v
                                ruta = _guardar_foto(color, "acceso")
                                cola_eventos.put({
                                    "tipo": "ACCESO_PERMITIDO",
                                    "nombre": nombre_v,
                                    "usuario_id": uid_v,
                                    "confianza": conf_v,
                                    "metricas": metricas,
                                    "foto_ruta": ruta,
                                    "frame": color.copy()
                                })
                        elif track.sesion_tipo != "DESCONOCIDO":
                            track.sesion_tipo = "DESCONOCIDO"
                            track.sesion_sujeto = None
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
                    t.t_proximo_embedding = 0  # Forzar re-evaluación inmediata
                    t.limpiar_votos()
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
                    t.t_proximo_embedding = 0
                    t.limpiar_votos()
                    t.nombre = None
                    t.confianza = 0
                print(f"    Caché recargada (invalidación externa): {len(usuarios)} usuarios")

            # Recarga periódica automática cada 60s
            if ahora - t_cache_refresh >= CACHE_REFRESH_INTERVAL:
                t_cache_refresh = ahora
                usuarios = _cargar_usuarios_supabase()
                reconocedor.recargar_cache(usuarios)
                for t in tracks_activos:
                    t.t_proximo_embedding = 0
                    t.limpiar_votos()
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


def _procesar_registro(track, modo_registro, reconocedor, imagen_rgb, ahora,
                        reg_dir, reg_tiempo, reg_flash):
    """Helper para procesamiento de registro (placeholder para lógica inline)."""
    pass  # La lógica se maneja inline en el bucle principal


def _dormir_hasta_fps(frame_start, target_time):
    """Duerme lo necesario para no exceder el FPS objetivo."""
    elapsed = time.time() - frame_start
    if elapsed < target_time:
        time.sleep(target_time - elapsed)
