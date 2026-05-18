"""
Snapshot Uploader — Preview en vivo para el frontend.

Sube un frame JPEG comprimido a Supabase Storage cada N segundos.
El frontend lo consume como un <img> con polling (cache-busting).

El frame subido es el mismo que se muestra en cv2.imshow: ya incluye
los overlays de bbox, nombre, estado, métricas, etc.

Diseño:
  - Se ejecuta en fire-and-forget threads para no bloquear el pipeline.
  - Sobreescribe siempre el mismo archivo (upsert) para ahorrar storage.
  - Resize a 480px de ancho + JPEG quality 50 → ~20-40KB por frame.
"""

import cv2
import threading

from backend.supabase_cliente import obtener_cliente

# Nombre fijo del archivo en Storage (se sobreescribe cada vez)
_SNAPSHOT_FILENAME = "live_preview.jpg"
_STORAGE_BUCKET = "capturas"

# Calidad JPEG (0-100). 50 es buen balance entre calidad y tamaño (~25KB)
_JPEG_QUALITY = 50

# Ancho máximo del snapshot en pixeles
_MAX_WIDTH = 480

# Lock para evitar uploads concurrentes
_upload_lock = threading.Lock()


def subir_snapshot(frame):
    """
    Sube un frame como snapshot a Supabase Storage.
    Llamar en un hilo daemon (fire-and-forget) para no bloquear el pipeline.
    
    El frame ya debe tener los overlays dibujados (bbox, nombre, etc.).
    """
    if frame is None:
        return

    # No bloquear si ya hay un upload en progreso
    if not _upload_lock.acquire(blocking=False):
        return

    try:
        # Resize para reducir bandwidth
        h, w = frame.shape[:2]
        if w > _MAX_WIDTH:
            scale = _MAX_WIDTH / w
            frame = cv2.resize(frame, (_MAX_WIDTH, int(h * scale)))

        # Encode a JPEG en memoria
        _, buffer = cv2.imencode(
            '.jpg', frame,
            [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
        )
        jpeg_bytes = buffer.tobytes()

        # Subir a Supabase Storage con upsert (sobreescribe si existe)
        supabase = obtener_cliente()
        supabase.storage.from_(_STORAGE_BUCKET).upload(
            path=_SNAPSHOT_FILENAME,
            file=jpeg_bytes,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true",
            }
        )
    except Exception as e:
        # Silenciar errores — el snapshot es best-effort,
        # no debe afectar el pipeline principal
        error_str = str(e)
        if "Duplicate" not in error_str and "already exists" not in error_str:
            pass  # Solo loguear errores inesperados si se necesita debug
    finally:
        _upload_lock.release()
