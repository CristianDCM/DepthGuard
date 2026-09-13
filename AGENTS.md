# DepthGuard - Agent Instructions

## Quick Start

```powershell
.\venv\Scripts\activate
python iniciar.py
```

## Architecture

- **Entry point**: `iniciar.py` - starts 3 daemon threads
- **Thread 1**: IA pipeline (infinite loop) — camera → detection → antispoofing → recognition
- **Thread 2**: Supabase sync — reads `queue.Queue`, INSERTs into `historial` table (store-and-forward)
- **Thread 3**: Heartbeat — updates `estado_sistema.ultimo_heartbeat` every 30s
- **No HTTP server** — this is a pure edge client that pushes data to Supabase Cloud

## Camera Modes

Set `MODO_CAMARA` in `.env`:
- `simulada` - webcam + synthetic depth (default)
- `realsense` - Intel RealSense D400 (requires pyrealsense2)

## Key Files

| File | Purpose |
|------|---------|
| `iniciar.py` | Entry point, starts 3 threads (IA + sync + heartbeat) |
| `motor_ia/pipeline.py` | Orchestrator: camera → detection → antispoofing → recognition |
| `motor_ia/tracking.py` | `PersonaTrack` (incl. temporal voting) + IoU association across frames |
| `motor_ia/camara/factory.py` | Camera factory based on MODO_CAMARA |
| `backend/supabase_cliente.py` | Supabase client singleton (service_role key) |
| `backend/supabase_sync.py` | Store-and-forward: queue → Supabase historial |
| `backend/heartbeat.py` | Updates estado_sistema.ultimo_heartbeat every 30s |
| `config/settings.py` | Loads `.env`, exports all config vars |

## Dependencies

- Requires Intel RealSense SDK if `MODO_CAMARA=realsense`
- Requires `.env` file with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
- Supabase tables must be created beforehand (see DISEÑO_SISTEMA.md)

## Recognition accuracy

Tunable via `.env` (defaults in `config/settings.py`):

| Variable | What it does |
|----------|--------------|
| `TOLERANCIA_FACIAL` | Max distance to accept an identity |
| `MARGEN_IDENTIDAD` | Minimum separation between the best identity and the runner-up. A tie is rejected instead of guessed. Higher = fewer false positives |
| `VOTOS_VENTANA` / `VOTOS_REQUERIDOS` | Temporal voting: a single embedding never emits an event; N agreeing inferences are required |
| `COOLDOWN_EMBEDDING_VOTACION` | Fast cadence while voting is still deciding |
| `COOLDOWN_EMBEDDING` | Slow cadence once a verdict exists (re-confirmation only) |
| `MAX_EMBEDDINGS_POR_FRAME` | Per-frame embedding budget. The loop is single-threaded and one embedding costs ~50-150 ms, so this bounds frame time when several people are in view |
| `MAX_YAW_RECONOCIMIENTO` / `MAX_PITCH_RECONOCIMIENTO` | Recognition is skipped outside this pose range |
| `PENALIZACION_POSE` | Penalty for templates captured at a different angle. A soft tie-breaker, not a filter |
| `ESCALA_CONFIANZA` | Width of the distance → confidence sigmoid. Confidence is exactly 0.50 at `TOLERANCIA_FACIAL` |
| `JITTERS_REGISTRO` | Transformations dlib averages when building a template (runs once per angle) |

Design notes:

- Detection runs on the frame downscaled to 640px, but the **embedding is cropped
  from the native-resolution frame** (`escalar_bbox`) — a distant face gains
  pixels with no extra detection cost.
- Quality gates are evaluated on the **downscaled** frame on purpose, so the
  pixel thresholds mean the same thing on any camera.
- Each template's angle is derived from capture order (`embeddings_json[i]` ↔
  `ANGULOS_REGISTRO[i]`), so no database migration is needed.

## Admin

- Default: `admin` / `admin123` (from `.env`)
- Create additional admins: `python scripts/crear_admin.py`

## Database

- **Supabase PostgreSQL** (cloud) — no local database
- Tables: `admin`, `usuarios`, `historial`, `estado_sistema`, `suscripciones_push`
- Edge uses `service_role` key to bypass RLS

## Frontend

- Frontend is a separate React PWA deployed on Vercel
- Not included in this repository
- Communicates with Supabase directly (Realtime + SDK)

## Useful Commands

```powershell
# Create admin in Supabase
python scripts/crear_admin.py
```

## Notes

- `cv2.imshow` blocks in the pipeline loop; press 'q' to exit the preview window
- System design doc: `DISEÑO_SISTEMA.md`
- Store-and-forward buffers up to 500 events during internet outages

