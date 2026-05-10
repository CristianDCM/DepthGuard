# 🛡️ DepthGuard — Nodo Edge

Sistema de control de acceso biométrico con detección anti-spoofing 3D.

## ¿Qué hace?

DepthGuard es el **nodo edge** que corre en un PC con cámaras. Detecta rostros, verifica autenticidad 3D y envía los resultados a **Supabase Cloud** en tiempo real:

- **Detectar rostros** con MediaPipe Face Mesh
- **Verificar autenticidad 3D** analizando el mapa de profundidad (anti-spoofing)
- **Reconocer personas** comparando embeddings faciales (face_recognition)
- **Sincronizar con Supabase** — eventos, heartbeat y estado de cámaras
- **Store-and-Forward** — tolerancia a cortes de internet

> **Nota:** Este repositorio es solo el nodo edge (cámaras + IA). El frontend admin está en un repo separado desplegado en Vercel.

## Arquitectura

```
┌─────────────────────────────────┐
│  Nodo Edge (este repo)          │
│  ├── Hilo 1: Pipeline IA       │
│  ├── Hilo 2: Sync Supabase     │
│  └── Hilo 3: Heartbeat (30s)   │
└──────────────┬──────────────────┘
               │ supabase-py (HTTPS)
               ▼
┌──────────────────────────────────┐
│  Supabase Cloud (PostgreSQL)     │
│  └── Realtime → Frontend Vercel  │
└──────────────────────────────────┘
```

## Requisitos previos

- Python 3.10+
- Webcam (modo simulado) o Intel RealSense D400 (modo real)
- Cuenta de Supabase con las tablas creadas
- Sistema operativo: Windows / Linux

## Instalación

```powershell
# Clonar el repositorio
git clone https://github.com/CristianDCM/DepthGuard.git
cd DepthGuard

# Crear entorno virtual
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
copy .env.example .env  # Windows
# cp .env.example .env  # Linux
```

Edita `.env` y agrega tus credenciales de Supabase:
```
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_SERVICE_KEY=eyJ...tu-service-role-key...
```

## Instalación rápida (Windows)

1. Asegúrate de tener **Python 3.10+** instalado ([descargar](https://www.python.org/downloads/))
2. Haz doble clic en **`INSTALAR.bat`** — crea el entorno virtual e instala todo
3. Edita **`.env`** con tus credenciales de Supabase
4. Haz doble clic en **`INICIAR.bat`** — arranca el sistema

## Uso manual

```powershell
.\venv\Scripts\activate
python iniciar.py
```

La aplicación inicia tres hilos:
1. **Pipeline IA** — cámara → detección → anti-spoofing → reconocimiento
2. **Sync Supabase** — eventos del pipeline → INSERT en tabla `historial`
3. **Heartbeat** — actualiza `estado_sistema.ultimo_heartbeat` cada 30s

## Modos de cámara

Configurar `MODO_CAMARA` en `.env`:

| Modo | Descripción |
|------|-------------|
| `simulada` | Webcam + profundidad sintética (default) |
| `realsense` | Intel RealSense D400 (requiere pyrealsense2) |

## Estructura del proyecto

```
DepthGuard/
├── INSTALAR.bat               # 🔧 Instalador automático
├── INICIAR.bat                # 🚀 Lanzador del sistema
├── iniciar.py                 # Punto de entrada (3 hilos)
├── config/
│   └── settings.py            # Configuración (.env)
├── motor_ia/
│   ├── pipeline.py            # Orquestador principal
│   ├── visualizacion.py       # Preview de debug
│   ├── estado_registro.py     # Estado thread-safe del registro
│   ├── camara/                # Factory: simulada / realsense
│   ├── deteccion/             # Face Mesh (MediaPipe)
│   ├── antispoofing/          # Verificación 3D
│   └── reconocimiento/        # Embeddings faciales
├── backend/
│   ├── supabase_cliente.py    # Cliente Supabase (singleton)
│   ├── supabase_sync.py       # Store-and-Forward → historial
│   └── heartbeat.py           # Heartbeat cada 30s
├── scripts/
│   └── crear_admin.py         # Crear admin en Supabase
└── tests/                     # Tests unitarios
```

## Scripts útiles

```powershell
# Crear admin adicional en Supabase
python scripts/crear_admin.py
```

## Admin por defecto

- **Usuario:** `admin`
- **Contraseña:** `admin123`

Cambiar en `.env` (`ADMIN_USUARIO`, `ADMIN_PASSWORD`).

## Licencia

MIT

