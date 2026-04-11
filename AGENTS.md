# DepthGuard - Agent Instructions

## Quick Start

```powershell
.\venv\Scripts\activate
python iniciar.py
```

## Architecture

- **Entry point**: `iniciar.py` - starts IA pipeline in daemon thread + FastAPI server
- **Two main threads**: IA pipeline (infinite loop) + FastAPI with internal queue processor
- **Communication**: `queue.Queue` for IA → Backend events

## Camera Modes

Set `MODO_CAMARA` in `.env`:
- `simulada` - webcam + synthetic depth (default)
- `realsense` - Intel RealSense D400 (requires pyrealsense2)

## Key Files

| File | Purpose |
|------|---------|
| `iniciar.py` | Entry point, threads IA + FastAPI |
| `motor_ia/pipeline.py` | Orchestrator: camera → detection → antispoofing → recognition |
| `motor_ia/camara/factory.py` | Camera factory based on MODO_CAMARA |
| `backend/servidor.py` | FastAPI API + WebSocket + queue processor |
| `backend/base_datos.py` | SQLite (WAL mode): admin, usuarios_biometricos, historial |
| `config/settings.py` | Loads `.env`, exports all config vars |

## Dependencies

- Requires Intel RealSense SDK if `MODO_CAMARA=realsense`
- Requires `.env` file (copy from `.env.example`)
- Push notifications require VAPID keys (generate with `scripts/generar_llaves_vapid.py`)

## Admin

- Default: `admin` / `admin123` (from `.env`)
- Create additional admins: `python scripts/crear_admin.py`

## Database

- Location: `backend/database.db` (SQLite with WAL)
- Tables: `admin`, `usuarios_biometricos` (embeddings JSON), `historial`, `suscripciones_push`

## UI

Frontend PWA served at `/` via FastAPI static files from `frontend_pwa/public/`

## Useful Commands

```powershell
# Create VAPID keys for push notifications
python scripts/generar_llaves_vapid.py

# Run admin creation script
python scripts/crear_admin.py
```

## Notes

- `cv2.imshow` blocks in the pipeline loop; press 'q' to exit the preview window
- Walkthrough doc: `walkthrough.md`
