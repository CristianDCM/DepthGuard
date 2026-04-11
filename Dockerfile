# ============================================
# DEPTHGUARD - Dockerfile
# ============================================
# Construir:  docker build -t depthguard .
# Ejecutar:   docker run --env-file .env -p 8000:8000 depthguard
# ============================================

FROM python:3.10-slim

# ── Dependencias del sistema ──────────────────
# cmake + build-essential: compilar dlib/face_recognition
# libgl1 + libglib2.0-0: OpenCV headless
# libsm6 + libxext6 + libxrender1: rendering libs para mediapipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# ── Directorio de trabajo ─────────────────────
WORKDIR /app

# ── Instalar dependencias Python ──────────────
# Copiamos solo requirements.txt primero para aprovechar cache de Docker
COPY requirements.txt .

# Instalar dependencias (excluyendo pyrealsense2 que necesita hardware)
RUN pip install --no-cache-dir \
    $(grep -v pyrealsense2 requirements.txt | tr '\n' ' ')

# ── Copiar código fuente ──────────────────────
COPY . .

# ── Crear directorio de capturas ──────────────
RUN mkdir -p backend/capturas

# ── Puerto expuesto ───────────────────────────
EXPOSE 8000

# ── Variables de entorno por defecto ──────────
# Forzar modo simulada (no hay cámara física en Docker)
ENV MODO_CAMARA=simulada
# Desactivar buffering de Python para ver logs en tiempo real
ENV PYTHONUNBUFFERED=1

# ── Comando de inicio ────────────────────────
CMD ["python", "iniciar.py"]
