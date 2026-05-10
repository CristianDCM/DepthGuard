@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
title DepthGuard - Instalador
color 0B

set LOG_FILE=install_log.txt

:: Inicializar log
echo ========================================================= > "%LOG_FILE%"
echo   LOG DE INSTALACION DEPTHGUARD >> "%LOG_FILE%"
echo   Fecha: %date% %time% >> "%LOG_FILE%"
echo ========================================================= >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo.
echo =========================================================
echo   DEPTHGUARD - INSTALADOR AUTOMATICO
echo   Sistema de Control de Acceso Biometrico 3D
echo =========================================================
echo.
echo   Este script prepara todo el entorno necesario.
echo   Registro de errores en: %LOG_FILE%
echo.
pause

:: -----------------------------------------------
:: PASO 1: Verificar que Python existe
:: -----------------------------------------------
echo.
echo  [1/6] Verificando Python...              [##........] 16%%
echo [PASO 1] Verificando Python... >> "%LOG_FILE%"
python --version >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo.
    echo    [X] ERROR: Python no esta instalado o no esta en el PATH.
    echo [ERROR] Python no encontrado >> "%LOG_FILE%"
    echo.
    echo    Descargalo de: https://www.python.org/downloads/
    echo    IMPORTANTE: Marca la casilla "Add Python to PATH" al instalar.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo    [OK] Python %PYTHON_VER% encontrado
echo    [OK] Python %PYTHON_VER% >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 2: Crear entorno virtual
:: -----------------------------------------------
echo.
echo  [2/6] Creando entorno virtual...         [####......] 33%%
echo [PASO 2] Creando entorno virtual... >> "%LOG_FILE%"
if exist venv (
    echo    [~] Ya existe un entorno virtual. Se usara el existente.
    echo    [SKIP] Entorno virtual ya existe >> "%LOG_FILE%"
) else (
    python -m venv venv 2>> "%LOG_FILE%"
    if !errorlevel! neq 0 (
        echo    [X] ERROR: No se pudo crear el entorno virtual. Revisa %LOG_FILE%.
        echo [ERROR] Fallo al crear venv >> "%LOG_FILE%"
        pause
        exit /b 1
    )
    echo    [OK] Entorno virtual creado
    echo    [OK] Entorno virtual creado >> "%LOG_FILE%"
)

:: -----------------------------------------------
:: PASO 3: Activar entorno virtual
:: -----------------------------------------------
echo.
echo  [3/6] Activando entorno virtual...       [######....] 50%%
echo [PASO 3] Activando entorno virtual... >> "%LOG_FILE%"
call venv\Scripts\activate.bat 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] ERROR: No se pudo activar el entorno virtual. Revisa %LOG_FILE%.
    echo [ERROR] Fallo al activar venv >> "%LOG_FILE%"
    pause
    exit /b 1
)
echo    [OK] Entorno virtual activado
echo    [OK] Entorno virtual activado >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 4: Actualizar pip
:: -----------------------------------------------
echo.
echo  [4/6] Actualizando pip...                [########..] 66%%
echo [PASO 4] Actualizando pip... >> "%LOG_FILE%"
python -m pip install --upgrade pip --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [~] Hubo un problema actualizando pip. Revisa %LOG_FILE%.
    echo [WARN] pip upgrade fallo >> "%LOG_FILE%"
) else (
    echo    [OK] pip actualizado
    echo    [OK] pip actualizado >> "%LOG_FILE%"
)

:: -----------------------------------------------
:: PASO 5: Instalar dependencias
:: -----------------------------------------------
echo.
echo  [5/6] Instalando dependencias...         [#########.] 83%%
echo.
echo    Esto puede tardar varios minutos la primera vez.
echo    Si hay errores, se guardaran en %LOG_FILE%.
echo.
echo [PASO 5] Instalando dependencias... >> "%LOG_FILE%"

:: --- 5a: dlib precompilado ---
echo    ^> [5a] dlib (precompilado)...
echo    [5a] Instalando dlib-bin... >> "%LOG_FILE%"
pip install dlib-bin --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [~] dlib-bin fallo. Intentando con dlib normal...
    echo    [WARN] dlib-bin fallo, intentando dlib source >> "%LOG_FILE%"
    pip install dlib --quiet 2>> "%LOG_FILE%"
    if !errorlevel! neq 0 (
        echo    [X] dlib tambien fallo. Necesitas Microsoft C++ Build Tools.
        echo    [ERROR] dlib source tambien fallo >> "%LOG_FILE%"
    ) else (
        echo    [OK] dlib instalado (desde source)
        echo    [OK] dlib instalado - source >> "%LOG_FILE%"
    )
) else (
    echo    [OK] dlib-bin instalado
    echo    [OK] dlib-bin instalado >> "%LOG_FILE%"
)

:: --- 5b: numpy ---
echo    ^> [5b] numpy...
echo    [5b] Instalando numpy... >> "%LOG_FILE%"
pip install numpy==1.24.4 --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] numpy fallo. Revisa %LOG_FILE%.
    echo    [ERROR] numpy fallo >> "%LOG_FILE%"
) else (
    echo    [OK] numpy instalado
    echo    [OK] numpy instalado >> "%LOG_FILE%"
)

:: --- 5c: opencv ---
echo    ^> [5c] OpenCV...
echo    [5c] Instalando opencv-python... >> "%LOG_FILE%"
pip install opencv-python==4.8.1.78 --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] opencv-python fallo. Revisa %LOG_FILE%.
    echo    [ERROR] opencv-python fallo >> "%LOG_FILE%"
) else (
    echo    [OK] OpenCV instalado
    echo    [OK] opencv-python instalado >> "%LOG_FILE%"
)

:: --- 5d: mediapipe ---
echo    ^> [5d] MediaPipe...
echo    [5d] Instalando mediapipe... >> "%LOG_FILE%"
pip install mediapipe==0.10.14 --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] mediapipe fallo. Revisa %LOG_FILE%.
    echo    [ERROR] mediapipe fallo >> "%LOG_FILE%"
) else (
    echo    [OK] MediaPipe instalado
    echo    [OK] mediapipe instalado >> "%LOG_FILE%"
)

:: --- 5e: face-recognition (sin dlib como dep, ya que usamos dlib-bin) ---
echo    ^> [5e] face-recognition...
echo    [5e] Instalando face-recognition (--no-deps)... >> "%LOG_FILE%"
pip install face-recognition==1.3.0 --no-deps --quiet 2>> "%LOG_FILE%"
pip install face_recognition_models --quiet 2>> "%LOG_FILE%"
pip install click --quiet 2>> "%LOG_FILE%"
pip install Pillow --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] face-recognition fallo. Revisa %LOG_FILE%.
    echo    [ERROR] face-recognition fallo >> "%LOG_FILE%"
) else (
    echo    [OK] face-recognition instalado
    echo    [OK] face-recognition instalado >> "%LOG_FILE%"
)

:: --- 5f: supabase ---
echo    ^> [5f] Supabase SDK...
echo    [5f] Instalando supabase... >> "%LOG_FILE%"
pip install supabase==2.15.2 --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [X] supabase fallo. Revisa %LOG_FILE%.
    echo    [ERROR] supabase fallo >> "%LOG_FILE%"
) else (
    echo    [OK] Supabase SDK instalado
    echo    [OK] supabase instalado >> "%LOG_FILE%"
)

:: --- 5g: pyrealsense2 (opcional) ---
echo    ^> [5g] pyrealsense2 (opcional)...
echo    [5g] Instalando pyrealsense2... >> "%LOG_FILE%"
pip install pyrealsense2==2.55.1.6486 --quiet 2>> "%LOG_FILE%"
if %errorlevel% neq 0 (
    echo    [~] pyrealsense2 no se pudo instalar. (Normal si no hay SDK).
    echo    [WARN] pyrealsense2 no instalado >> "%LOG_FILE%"
) else (
    echo    [OK] pyrealsense2 instalado
    echo    [OK] pyrealsense2 instalado >> "%LOG_FILE%"
)

echo.
echo    [OK] Dependencias procesadas
echo    [OK] Todas las dependencias procesadas >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 6: Configurar archivo .env
:: -----------------------------------------------
echo.
echo  [6/6] Configurando archivo .env...       [##########] 100%%
echo [PASO 6] Configurando archivo .env... >> "%LOG_FILE%"
if exist .env (
    echo    [~] Ya existe un archivo .env. No se sobreescribira.
    echo    [SKIP] .env ya existe >> "%LOG_FILE%"
) else (
    if exist .env.example (
        copy .env.example .env >nul 2>> "%LOG_FILE%"
        echo    [OK] Archivo .env creado desde .env.example
        echo    [OK] .env creado desde .env.example >> "%LOG_FILE%"
        echo    Edita el archivo .env para configurar tus credenciales.
    ) else (
        echo    [X] No se encontro .env.example para copiar.
        echo    [ERROR] No se encontro .env.example >> "%LOG_FILE%"
    )
)

:: -----------------------------------------------
:: VERIFICACION FINAL
:: -----------------------------------------------
echo.
echo -------------------------------------------------
echo   Verificando modulos criticos...
echo -------------------------------------------------
echo. >> "%LOG_FILE%"
echo [VERIFICACION] Comprobando imports criticos... >> "%LOG_FILE%"

set INSTALL_OK=1

python -c "import cv2" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] cv2 - OpenCV - NO disponible
    echo    [FAIL] import cv2 >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] cv2 - OpenCV
    echo    [PASS] import cv2 >> "%LOG_FILE%"
)

python -c "import mediapipe" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] mediapipe NO disponible
    echo    [FAIL] import mediapipe >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] mediapipe
    echo    [PASS] import mediapipe >> "%LOG_FILE%"
)

python -c "import face_recognition" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] face_recognition NO disponible
    echo    [FAIL] import face_recognition >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] face_recognition
    echo    [PASS] import face_recognition >> "%LOG_FILE%"
)

python -c "import numpy" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] numpy NO disponible
    echo    [FAIL] import numpy >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] numpy
    echo    [PASS] import numpy >> "%LOG_FILE%"
)

python -c "import supabase" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] supabase NO disponible
    echo    [FAIL] import supabase >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] supabase
    echo    [PASS] import supabase >> "%LOG_FILE%"
)

python -c "import dlib" 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] dlib NO disponible
    echo    [FAIL] import dlib >> "%LOG_FILE%"
    set INSTALL_OK=0
) else (
    echo    [OK] dlib
    echo    [PASS] import dlib >> "%LOG_FILE%"
)

:: -----------------------------------------------
:: LISTO
:: -----------------------------------------------
echo.
if "!INSTALL_OK!"=="1" (
    echo =========================================================
    echo   INSTALACION COMPLETADA EXITOSAMENTE
    echo =========================================================
    echo    [RESULTADO] Instalacion exitosa >> "%LOG_FILE%"
) else (
    echo =========================================================
    echo   INSTALACION CON PROBLEMAS
    echo =========================================================
    echo    [RESULTADO] Instalacion con fallos >> "%LOG_FILE%"
    echo.
    echo   Algunos modulos no se instalaron correctamente.
    echo   Revisa el log: %LOG_FILE%
)
echo.
echo   Log guardado en: %LOG_FILE%
echo   Para iniciar el sistema, ejecuta: INICIAR.bat
echo.
echo   Notas:
echo   - Edita .env y agrega tus credenciales de Supabase
echo   - Si usas RealSense, cambia MODO_CAMARA=realsense en .env
echo   - Admin por defecto: admin / admin123
echo.
pause
endlocal
