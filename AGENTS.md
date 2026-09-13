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
| `backend/supabase_cliente.py` | Supabase client singleton (restricted device key) |
| `backend/claves.py` | Key-selection policy: restricted key wins, service_role fails closed |
| `backend/privilegios.py` | Authoritative inventory of every privileged op the edge performs |
| `backend/autorizacion_registro.py` | Authorizes enrolment commands before the edge writes biometrics |
| `backend/almacenamiento.py` | Storage access: public vs signed URLs for capture images |
| `supabase/rls_edge.sql` | Restricted role + RLS policies implementing that inventory |
| `backend/postura_seguridad.py` | Startup security-posture report; `MODO_PRODUCCION` makes findings fatal |
| `backend/supabase_sync.py` | Store-and-forward: queue → Supabase historial |
| `backend/heartbeat.py` | Updates estado_sistema.ultimo_heartbeat every 30s |
| `config/settings.py` | Loads `.env`, exports all config vars |

## Dependencies

- Requires Intel RealSense SDK if `MODO_CAMARA=realsense`
- Requires `.env` file with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
- Supabase tables must be created beforehand (see DISEÑO_SISTEMA.md)

## Security posture at startup

Every audit fix ships with a setting, and most default to the insecure value so
existing installs keep working. That leaves an operational risk: the repo is
fixed while production keeps running the development configuration, because
nobody reads one warning buried in a hundred lines of log.

`backend/postura_seguridad.py` gathers all of them into one report printed at
startup, each finding tagged with its audit id (C1, C3, C4, C5, C6), its
severity and its remedy.

| Variable | What it does |
|----------|--------------|
| `MODO_PRODUCCION` | `true` makes any CRITICO or ALTO finding **abort startup** instead of warning. Set it in real deployments — a system that refuses to start gets fixed today; a warning gets ignored for months |

Target configuration for a real deployment is listed at the bottom of
`.env.example`.

## Capture storage (biometric images)

The `capturas` bucket was public and the code used `get_public_url()`. Face
photos from every access event, and the live preview frame, sat at URLs with
**no authentication and no expiry** — the preview at a fixed, guessable path
refreshed every 2s. These are images of identified people.

All storage access now goes through `backend/almacenamiento.py`, which serves
either public or **signed, expiring** URLs based on `STORAGE_PRIVADO`.
`tests/test_privilegios.py` enforces that `get_public_url` appears nowhere else,
so no code path can quietly bypass that decision.

| Variable | What it does |
|----------|--------------|
| `STORAGE_PRIVADO` | `false` (default) keeps the legacy public URLs and warns at startup. `true` issues signed URLs that expire |

Signed URL lifetimes: event photos get `DIAS_RETENCION + 1` days, so a URL
never expires *before* cleanup deletes its record (which would leave holes in
the history). The preview gets 1 hour, renewed by every heartbeat.

**Turning it on takes three steps, in this order:**

1. Change the frontend to read `preview_url` from the active camera in
   `estado_sistema.camaras` instead of building the preview URL from the file
   name. Event photos need **no** frontend change — `historial.foto_url` is
   still a URL, just a signed one.
2. Apply `supabase/rls_edge.sql` section 4 (flips the bucket to private).
3. Set `STORAGE_PRIVADO=true`.

Doing step 2 before step 1 leaves the live preview blank.

The filename is not a security control and is not treated as one: privacy
comes from the bucket policy. Once the bucket is private, a guessable path is
harmless.

## Enrolment authorization

The edge used to enrol biometrics into whatever `usuario_id` a row in
`comandos_edge` carried, with no validation. Anyone able to insert such a row
made the edge **overwrite an administrator's face templates with their own** —
direct impersonation, not privilege escalation.

Every `INICIAR_REGISTRO` command is now authorized before anything is written:

1. The target must **exist and be active** — the edge reads `usuarios` itself
   rather than trusting the command.
2. If the command states a `nombre`, it must **match the database**. This stops
   an attacker disguising "overwrite the admin" as "enrol a new employee": they
   must use the admin's real name, which then shows in the HUD and the audit
   record. The DB name is always the authoritative one displayed.
3. **Re-enrolment is blocked** — overwriting existing templates needs explicit
   authorization the attacker cannot grant themselves.

| Variable | What it does |
|----------|--------------|
| `PERMITIR_REENROLAMIENTO` | Local device config. Without a signature this is the **only** thing an attacker does not control (the command's own flag, they do). Keep it `false`; turn it on only for the duration of a legitimate re-enrolment |
| `REGISTRO_HMAC_SECRET` | Shared secret for signed commands. Empty = no signature required. Sign **server-side** (a Supabase Edge Function or the admin backend), never in the browser |

The signed message is `tipo|id|usuario_id|nombre|reenrolar` (HMAC-SHA256, hex).
The command id is inside it, so a valid signature cannot be transplanted onto
another row; the re-enrolment flag is inside it too, so it cannot be flipped
after signing.

**Scope, honestly:** this closes an attacker who can write to `comandos_edge`
but not insert into `usuarios`. One who can do both can create an identity and
enrol into it — that is cut off by the `usuarios` RLS, not here. And since the
edge needs the HMAC secret to verify, a compromised *edge* can forge commands;
the signature protects against a compromised *database*.

## Supabase keys / least privilege

**Do not put the service_role key on the device.** It bypasses ALL RLS by
design: anyone who reads that machine's `.env` gets full control of the
project — every user, every biometric template, the whole history, unrestricted
writes. Nothing the edge does needs that (see `backend/privilegios.py`).

| Variable | What it does |
|----------|--------------|
| `SUPABASE_EDGE_KEY` | The device key, restricted by RLS. **Use this.** Generate it with `supabase/rls_edge.sql` |
| `SUPABASE_ANON_KEY` | Public key, used for the WebRTC signalling channel (Broadcast only — it touches no table) |
| `SUPABASE_SERVICE_KEY` | Legacy. Only used when no edge key is set, and startup warns loudly |
| `PERMITIR_SERVICE_KEY` | Set `false` in production: the edge then refuses to start on service_role instead of running with a master key |
| `CLEANUP_EN_EDGE` | Set `false` with a restricted key. Deleting history is a privilege the device should not hold — a compromised edge could erase the audit trail. Move retention to pg_cron (see the SQL file) |

`tests/test_privilegios.py` scans the code for `.table()` / `.storage` calls
and fails if any is not declared in `backend/privilegios.py`. Adding a new
privileged call therefore forces a look at the RLS policies, instead of the
policies silently falling behind what the code asks for.

Migration is config-only once the SQL is applied: set `SUPABASE_EDGE_KEY`,
`PERMITIR_SERVICE_KEY=false`, `CLEANUP_EN_EDGE=false`.

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

**No default credentials, deliberately.** This repo used to publish
`admin` / `admin123`, which made it a known credential rather than a default,
and `config/settings.py` fell back to it whenever `.env` was missing.

Admin credentials are **not an edge concern** — authentication lives in the
frontend / Supabase, and no edge code ever read those variables. The `admin`
table is in `TABLAS_PROHIBIDAS` (`backend/privilegios.py`) for the same reason.
If `ADMIN_USUARIO` / `ADMIN_PASSWORD` are still in a device's `.env`, the
startup posture report flags it.

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

