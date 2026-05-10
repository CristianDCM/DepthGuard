@echo off
chcp 65001 >nul
title DepthGuard - Instalador
color 0B

echo.
echo =========================================================
echo   🛡️  DEPTHGUARD - INSTALADOR AUTOMATICO
echo   Sistema de Control de Acceso Biometrico 3D
echo =========================================================
echo.
echo   Este script prepara todo el entorno necesario.
echo   Solo necesitas tener Python 3.10+ instalado.
echo.
pause

:: ─────────────────────────────────────────────
:: PASO 1: Verificar que Python existe
:: ─────────────────────────────────────────────
echo.
echo [1/6] Verificando Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ❌ ERROR: Python no esta instalado o no esta en el PATH.
    echo.
    echo    Descargalo de: https://www.python.org/downloads/
    echo    IMPORTANTE: Marca la casilla "Add Python to PATH" al instalar.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo    ✅ Python %PYTHON_VER% encontrado

:: ─────────────────────────────────────────────
:: PASO 2: Crear entorno virtual
:: ─────────────────────────────────────────────
echo.
echo [2/6] Creando entorno virtual...
if exist venv (
    echo    ⚠️  Ya existe un entorno virtual. Se usara el existente.
    echo    Si deseas recrearlo, elimina la carpeta "venv" y ejecuta este script de nuevo.
) else (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ❌ ERROR: No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    echo    ✅ Entorno virtual creado
)

:: ─────────────────────────────────────────────
:: PASO 3: Activar entorno virtual
:: ─────────────────────────────────────────────
echo.
echo [3/6] Activando entorno virtual...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo ❌ ERROR: No se pudo activar el entorno virtual.
    pause
    exit /b 1
)
echo    ✅ Entorno virtual activado

:: ─────────────────────────────────────────────
:: PASO 4: Actualizar pip
:: ─────────────────────────────────────────────
echo.
echo [4/6] Actualizando pip...
python -m pip install --upgrade pip --quiet
echo    ✅ pip actualizado

:: ─────────────────────────────────────────────
:: PASO 5: Instalar dependencias
:: ─────────────────────────────────────────────
echo.
echo [5/6] Instalando dependencias...
echo.
echo    Esto puede tardar varios minutos la primera vez.
echo    (dlib y face-recognition son las mas pesadas)
echo.

:: Instalar dlib-bin primero (precompilado, no necesita Build Tools)
echo    → Instalando dlib (precompilado)...
pip install dlib-bin --quiet 2>nul
if %errorlevel% neq 0 (
    echo    ⚠️  dlib-bin fallo. Intentando con dlib normal...
    echo    (Esto puede requerir Microsoft C++ Build Tools)
    pip install dlib --quiet
)

:: Instalar el resto de dependencias (excepto pyrealsense2 que se instala aparte)
echo    → Instalando OpenCV, MediaPipe, Supabase y demas...
pip install numpy==1.24.4 --quiet
pip install opencv-python==4.8.1.78 --quiet
pip install mediapipe==0.10.14 --quiet
pip install face-recognition==1.3.0 --quiet
pip install supabase==2.15.2 --quiet

:: Instalar pyrealsense2 por separado (puede fallar si no hay SDK)
echo    → Instalando pyrealsense2 (camara Intel RealSense)...
pip install pyrealsense2==2.55.1.6486 --quiet 2>nul
if %errorlevel% neq 0 (
    echo    ⚠️  pyrealsense2 no se pudo instalar.
    echo       Esto es normal si no tienes el Intel RealSense SDK.
    echo       El modo "simulada" (webcam) funcionara sin problemas.
    echo       Si necesitas la camara RealSense, instala el SDK de:
    echo       https://www.intelrealsense.com/sdk-2/
)

echo.
echo    ✅ Dependencias instaladas

:: ─────────────────────────────────────────────
:: PASO 6: Configurar archivo .env
:: ─────────────────────────────────────────────
echo.
echo [6/6] Configurando archivo .env...
if exist .env (
    echo    ⚠️  Ya existe un archivo .env. No se sobreescribira.
) else (
    if exist .env.example (
        copy .env.example .env >nul
        echo    ✅ Archivo .env creado desde .env.example
        echo    📝 Edita el archivo .env para configurar tus credenciales.
    ) else (
        echo    ❌ No se encontro .env.example para copiar.
    )
)

:: ─────────────────────────────────────────────
:: LISTO
:: ─────────────────────────────────────────────
echo.
echo =========================================================
echo   ✅  INSTALACION COMPLETADA
echo =========================================================
echo.
echo   Para iniciar el sistema, ejecuta: INICIAR.bat
echo.
echo   Notas:
echo   - Edita .env y agrega tus credenciales de Supabase
echo   - Si usas RealSense, cambia MODO_CAMARA=realsense en .env
echo   - Admin por defecto: admin / admin123
echo.
pause
