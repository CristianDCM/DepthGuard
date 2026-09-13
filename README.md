#  DepthGuard — Nodo Edge

Sistema de control de acceso biométrico con detección anti-spoofing 3D.

## ¿Qué hace?

DepthGuard es el **nodo edge** que corre en un PC con cámaras. Detecta rostros, verifica autenticidad 3D y envía los resultados a **Supabase Cloud** en tiempo real:

- **Detectar rostros** con MediaPipe Face Mesh
- **Verificar autenticidad 3D** analizando el mapa de profundidad (solo con RealSense)
- **Prueba de vida 2D** por parpadeo, obligatoria para conceder acceso
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
SUPABASE_EDGE_KEY=eyJ...clave-de-dispositivo...
SUPABASE_ANON_KEY=eyJ...clave-publica...
PERMITIR_SERVICE_KEY=false
CLEANUP_EN_EDGE=false
```

> **Seguridad:** no pongas la `service_role` key en el dispositivo. Salta toda
> la RLS, así que quien lea ese `.env` obtiene control total del proyecto,
> incluidas todas las plantillas biométricas. Genera una clave de dispositivo
> restringida con [`supabase/rls_edge.sql`](supabase/rls_edge.sql). El sistema
> aún arranca con `service_role` por compatibilidad, pero avisa en cada inicio.

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

Al arrancar imprime un **informe de postura de seguridad** con los ajustes que
siguen en valores de desarrollo y cómo corregirlos. Con `MODO_PRODUCCION=true`,
los hallazgos graves **abortan el arranque** en lugar de quedarse en un aviso.

La aplicación inicia tres hilos:
1. **Pipeline IA** — cámara → detección → anti-spoofing → reconocimiento
2. **Sync Supabase** — eventos del pipeline → INSERT en tabla `historial`
3. **Heartbeat** — actualiza `estado_sistema.ultimo_heartbeat` cada 30s

## Modos de cámara

Configurar `MODO_CAMARA` en `.env`:

| Modo | Descripción |
|------|-------------|
| `simulada` | Webcam, **sin profundidad**. Anti-spoofing 3D no disponible: la prueba de vida es solo 2D (parpadeo) |
| `realsense` | Intel RealSense D400 (requiere pyrealsense2). Anti-spoofing 3D + liveness 2D |

> **Seguridad:** en despliegue real usa `realsense` y pon
> `REQUERIR_CAMARA_3D=true` en `.env`. Con webcam la única prueba de vida es
> el parpadeo, que detiene una foto impresa pero **no** un vídeo en bucle.

## Estructura del proyecto

```
DepthGuard/
├── INSTALAR.bat               #  Instalador automático
├── INICIAR.bat                #  Lanzador del sistema
├── iniciar.py                 # Punto de entrada (3 hilos)
├── config/
│   └── settings.py            # Configuración (.env)
├── motor_ia/
│   ├── pipeline.py            # Orquestador principal
│   ├── tracking.py            # Tracking IoU + votación temporal por persona
│   ├── visualizacion.py       # Preview de debug
│   ├── estado_registro.py     # Estado thread-safe del registro
│   ├── camara/                # Factory: simulada / realsense
│   ├── deteccion/             # Face Mesh (MediaPipe)
│   ├── antispoofing/          # Verificación 3D + liveness 2D (parpadeo)
│   └── reconocimiento/        # Embeddings faciales
├── supabase/
│   └── rls_edge.sql           # Rol restringido + políticas RLS del edge
├── backend/
│   ├── supabase_cliente.py    # Cliente Supabase (singleton)
│   ├── claves.py              # Política de selección de clave
│   ├── privilegios.py         # Inventario de privilegios del edge
│   ├── autorizacion_registro.py # Autoriza los comandos de enrolamiento
│   ├── almacenamiento.py      # URLs públicas vs firmadas de capturas
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

## Administradores

**No hay usuario ni contraseña por defecto, a propósito.** Este repositorio
publicaba `admin` / `admin123`, lo que convertía ese valor en una credencial
conocida por cualquiera que viera el repo.

Las credenciales de administrador **no son cosa del nodo edge**: la
autenticación vive en el frontend / Supabase. No pongas `ADMIN_USUARIO` ni
`ADMIN_PASSWORD` en el `.env` del edge — ningún código suyo las usa, y el
informe de postura del arranque te avisará si siguen ahí.

> Si tu instalación todavía usa `admin123`, **cámbiala ya**: está publicada en
> el historial de este repositorio.

## Licencia

MIT

