# 🛡️ DepthGuard

Sistema de control de acceso biométrico con detección anti-spoofing 3D.

## ¿Qué hace?

DepthGuard usa una cámara de profundidad (Intel RealSense) o una webcam en modo simulado para:

- **Detectar rostros** en tiempo real con MediaPipe Face Mesh
- **Verificar autenticidad 3D** analizando el mapa de profundidad (anti-spoofing)
- **Reconocer personas** comparando embeddings faciales (face_recognition)
- **Notificar alertas** por WebSocket y Web Push (PWA)

## Requisitos previos

- Python 3.10+
- Webcam (modo simulado) o Intel RealSense D400 (modo real)
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

## Uso

```powershell
.\venv\Scripts\activate
python iniciar.py
```

La aplicación inicia dos procesos:
1. **Pipeline IA** — bucle de cámara → detección → anti-spoofing → reconocimiento
2. **Servidor FastAPI** — API REST + WebSocket en `http://localhost:8000`

## Modos de cámara

Configurar `MODO_CAMARA` en `.env`:

| Modo | Descripción |
|------|-------------|
| `simulada` | Webcam + profundidad sintética (default) |
| `realsense` | Intel RealSense D400 (requiere pyrealsense2) |

## Estructura del proyecto

```
DepthGuard/
├── iniciar.py              # Punto de entrada
├── Dockerfile              # Imagen Docker
├── docker-compose.yml      # Orquestación de contenedores
├── .dockerignore           # Exclusiones para Docker
├── config/
│   └── settings.py         # Configuración centralizada (.env)
├── motor_ia/
│   ├── pipeline.py         # Orquestador principal
│   ├── visualizacion.py    # Preview de debug
│   ├── camara/             # Factory: simulada / realsense
│   ├── deteccion/          # Face Mesh (MediaPipe)
│   ├── antispoofing/       # Verificación 3D
│   └── reconocimiento/     # Embeddings faciales
├── backend/
│   ├── servidor.py         # FastAPI + WebSocket
│   ├── base_datos.py       # SQLite (WAL)
│   ├── modelos.py          # Pydantic schemas
│   └── notificaciones.py   # Web Push
├── frontend_pwa/
│   └── public/             # PWA estática
├── scripts/
│   ├── crear_admin.py      # Crear admin adicional
│   ├── generar_llaves_vapid.py
│   ├── servidor_push_test.py  # Test push notifications
│   └── iniciar_ngrok.bat
└── tests/                  # Tests unitarios
```

## Scripts útiles

```powershell
# Crear admin adicional
python scripts/crear_admin.py

# Generar llaves VAPID (push notifications)
python scripts/generar_llaves_vapid.py

# Test de push notifications
python scripts/servidor_push_test.py
```

## Admin por defecto

- **Usuario:** `admin`
- **Contraseña:** `admin123`

Cambiar en `.env` (`ADMIN_USUARIO`, `ADMIN_PASSWORD`).

## Docker

### Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado

### Ejecución con Docker

```bash
# Construir y levantar
docker-compose up --build

# Levantar en segundo plano
docker-compose up -d

# Ver logs
docker-compose logs -f

# Detener
docker-compose down

# Reconstruir después de cambios
docker-compose up --build
```

Docker ejecuta el proyecto en modo `simulada` automáticamente. Los datos (base de datos y capturas) se persisten en la carpeta `data/` mediante volúmenes.

> **Nota:** La primera construcción puede tardar varios minutos por la compilación de `dlib`.

## Licencia

MIT
