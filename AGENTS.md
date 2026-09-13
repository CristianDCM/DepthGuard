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
| `motor_ia/tracking.py` | `PersonaTrack` (incl. temporal voting + liveness state) + IoU association |
| `motor_ia/antispoofing/liveness.py` | 2D liveness: blink (EAR) + screen-texture metrics |
| `motor_ia/camara/factory.py` | Camera factory based on MODO_CAMARA |
| `backend/supabase_cliente.py` | Supabase client singleton (service_role key) |
| `backend/supabase_sync.py` | Store-and-forward: queue → Supabase historial |
| `backend/heartbeat.py` | Updates estado_sistema.ultimo_heartbeat every 30s |
| `config/settings.py` | Loads `.env`, exports all config vars |

## Dependencies

- Requires Intel RealSense SDK if `MODO_CAMARA=realsense`
- Requires `.env` file with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
- Supabase tables must be created beforehand (see DISEÑO_SISTEMA.md)

## Liveness / anti-spoofing

**The 3D check is only a liveness proof when depth comes from a real sensor.**
`CamaraSimulada` used to synthesize a depth map from the bbox the 2D detector
had just found, so the verifier validated a dome the system itself drew: any
detected face passed as real (printed photo included), always with identical
metrics. That synthetic depth is gone — the simulated camera now returns
`None` and declares `profundidad_real = False`.

Access now requires BOTH:

1. An identity verdict (temporal voting — see Recognition accuracy).
2. A liveness proof — `liveness_estado == VIVO`.

These are checked separately every frame, because the identity may be settled
before the person blinks; the access event fires when both land.

| Variable | What it does |
|----------|--------------|
| `REQUERIR_CAMARA_3D` | **Set to `true` in real deployments.** A camera without a depth sensor then grants nothing. Defaults to `false` so a webcam setup keeps working on 2D liveness alone |
| `LIVENESS_PARPADEOS_REQUERIDOS` | Blinks needed to pass |
| `LIVENESS_TIMEOUT` | Seconds in front of the camera with no blink before it counts as spoofing rather than "not yet" |
| `LIVENESS_FACTOR_CIERRE` / `_APERTURA` | Eye close/open thresholds as a fraction of that person's own baseline EAR (an absolute threshold fails on narrow eyes). The gap between them is hysteresis against landmark jitter |
| `LIVENESS_FRAMES_BASE` | Open-eye frames needed to learn the baseline |
| `LIVENESS_PARPADEO_MIN_FRAMES` / `_MAX_FRAMES` | Valid blink duration. The max matters: sustained closed eyes are not a blink |
| `LIVENESS_TEXTURA_BLOQUEA` | Whether screen-texture metrics can reject. **Default `false`** — these thresholds depend on your camera and lighting, and uncalibrated they reject legitimate people. Collect real `moire`/`especular` values from your events first |
| `LIVENESS_MOIRE_MAX` / `LIVENESS_ESPECULAR_MAX` | Texture thresholds once you enable blocking |

Every event records `metricas["verificacion"]` as `"3D+2D"` or `"2D"`, plus the
liveness metrics, so the audit trail says which layers actually verified.

**What this does NOT stop:** a looped video of the person (a video blinks).
Defeating replay and masks needs a real depth sensor, a passive PAD model
(e.g. MiniFASNet ONNX), or a randomized active challenge. Blink is the floor,
not the ceiling.

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

