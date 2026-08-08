@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
title DepthGuard - Instalador
color 0B

set LOG_FILE=install_log.txt
set PYTHON_CMD=
set PYTHON_VER=
set INSTALL_OK=1

:: Inicializar log
echo ========================================================= > "%LOG_FILE%"
echo   LOG DE INSTALACION DEPTHGUARD >> "%LOG_FILE%"
echo   Fecha: %date% %time% >> "%LOG_FILE%"
echo   Sistema: %OS% %PROCESSOR_ARCHITECTURE% >> "%LOG_FILE%"
echo ========================================================= >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo.
echo =========================================================
echo   DEPTHGUARD - INSTALADOR AUTOMATICO
echo   Sistema de Control de Acceso Biometrico 3D
echo =========================================================
echo.
echo   Este script prepara todo el entorno necesario.
echo   Registro detallado en: %LOG_FILE%
echo.
pause

:: -----------------------------------------------
:: PASO 1: DETECCION INTELIGENTE DE PYTHON
::         Cascada de 5 niveles + auto-instalacion
:: -----------------------------------------------
echo.
echo  [1/7] Detectando Python...                [#.........] 14%%
echo. >> "%LOG_FILE%"
echo [PASO 1] Deteccion inteligente de Python (cascada) >> "%LOG_FILE%"

:: ---- Nivel 1: py launcher (el mas confiable en Windows) ----
echo    Nivel 1: Buscando Python Launcher (py)...
echo    [N1] Probando py launcher... >> "%LOG_FILE%"
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py -3"
        for /f "tokens=2" %%i in ('py -3 --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Python Launcher encontrado: Python !PYTHON_VER!
        echo    [OK] N1: py -3 = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)
echo    [--] py launcher no disponible
echo    [SKIP] N1: py launcher no encontrado >> "%LOG_FILE%"

:: ---- Nivel 2: python en PATH (verificar que NO sea Windows Store) ----
echo    Nivel 2: Buscando python en PATH...
echo    [N2] Probando python en PATH... >> "%LOG_FILE%"
where python >nul 2>&1
if !errorlevel! equ 0 (
    :: Detectar trampa de Windows Store (App Execution Alias)
    for /f "tokens=*" %%p in ('where python 2^>nul') do (
        set "PYTHON_LOCATION=%%p"
        goto :check_store_trap
    )
    :check_store_trap
    echo !PYTHON_LOCATION! | findstr /i "WindowsApps" >nul 2>&1
    if !errorlevel! equ 0 (
        echo    [!!] DETECTADO: El comando 'python' abre la Microsoft Store.
        echo    [!!] Esto NO es Python real. Es un alias de Windows.
        echo    [WARN] N2: python es alias de Windows Store >> "%LOG_FILE%"
        goto :nivel3
    )
    :: Verificar que realmente funciona (no solo existe en PATH)
    python -c "import sys; print(sys.version)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        for /f "tokens=2" %%i in ('python --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Python en PATH: Python !PYTHON_VER!
        echo    [OK] N2: python = Python !PYTHON_VER! (ruta: !PYTHON_LOCATION!) >> "%LOG_FILE%"
        goto :python_encontrado
    ) else (
        echo    [--] python en PATH no responde correctamente
        echo    [WARN] N2: python existe en PATH pero no ejecuta >> "%LOG_FILE%"
    )
)
echo    [--] python no esta en PATH
echo    [SKIP] N2: python no encontrado en PATH >> "%LOG_FILE%"

:nivel3
:: ---- Nivel 3: python3 (alias alternativo) ----
echo    Nivel 3: Buscando python3...
echo    [N3] Probando python3... >> "%LOG_FILE%"
where python3 >nul 2>&1
if !errorlevel! equ 0 (
    python3 -c "import sys; print(sys.version)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python3"
        for /f "tokens=2" %%i in ('python3 --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] python3 encontrado: Python !PYTHON_VER!
        echo    [OK] N3: python3 = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)
echo    [--] python3 no disponible
echo    [SKIP] N3: python3 no encontrado >> "%LOG_FILE%"

:: ---- Nivel 4: Buscar en rutas comunes del disco ----
echo    Nivel 4: Buscando en rutas comunes del disco...
echo    [N4] Buscando en rutas comunes... >> "%LOG_FILE%"

:: Buscar en %LOCALAPPDATA%\Programs\Python\Python3XX\
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%d\python.exe" (
        set "PYTHON_CMD=%%d\python.exe"
        for /f "tokens=2" %%v in ('"%%d\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%v"
        echo    [OK] Encontrado en: %%d
        echo    [OK] N4: "%%d\python.exe" = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)

:: Buscar en C:\Python3XX\
for %%v in (313 312 311 310 39) do (
    if exist "C:\Python%%v\python.exe" (
        set "PYTHON_CMD=C:\Python%%v\python.exe"
        for /f "tokens=2" %%i in ('"C:\Python%%v\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Encontrado en: C:\Python%%v\
        echo    [OK] N4: C:\Python%%v\python.exe = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)

:: Buscar en %PROGRAMFILES%\Python3XX\
for %%v in (313 312 311 310 39) do (
    if exist "%PROGRAMFILES%\Python%%v\python.exe" (
        set "PYTHON_CMD=%PROGRAMFILES%\Python%%v\python.exe"
        for /f "tokens=2" %%i in ('"%PROGRAMFILES%\Python%%v\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Encontrado en: %PROGRAMFILES%\Python%%v\
        echo    [OK] N4: "%PROGRAMFILES%\Python%%v\python.exe" = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)

echo    [--] No encontrado en rutas comunes
echo    [SKIP] N4: No encontrado en disco >> "%LOG_FILE%"

:: ---- Nivel 5: Registro de Windows (PEP 514) ----
echo    Nivel 5: Buscando en Registro de Windows...
echo    [N5] Consultando registro (PEP 514)... >> "%LOG_FILE%"

:: Buscar en HKCU (instalacion por usuario)
for /f "tokens=*" %%k in ('reg query "HKCU\Software\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do (
    for /f "tokens=2,*" %%a in ("%%k") do (
        set "REG_PYTHON_PATH=%%b"
    )
)
if defined REG_PYTHON_PATH (
    if exist "!REG_PYTHON_PATH!\python.exe" (
        set "PYTHON_CMD=!REG_PYTHON_PATH!\python.exe"
        for /f "tokens=2" %%i in ('"!REG_PYTHON_PATH!\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Encontrado via registro HKCU: !REG_PYTHON_PATH!
        echo    [OK] N5: HKCU registry = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)

:: Buscar en HKLM (instalacion global)
for /f "tokens=*" %%k in ('reg query "HKLM\Software\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do (
    for /f "tokens=2,*" %%a in ("%%k") do (
        set "REG_PYTHON_PATH=%%b"
    )
)
if defined REG_PYTHON_PATH (
    if exist "!REG_PYTHON_PATH!\python.exe" (
        set "PYTHON_CMD=!REG_PYTHON_PATH!\python.exe"
        for /f "tokens=2" %%i in ('"!REG_PYTHON_PATH!\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Encontrado via registro HKLM: !REG_PYTHON_PATH!
        echo    [OK] N5: HKLM registry = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_encontrado
    )
)

echo    [--] No encontrado en registro de Windows
echo    [SKIP] N5: No encontrado en registro >> "%LOG_FILE%"

:: ---- PYTHON NO ENCONTRADO EN NINGUN NIVEL ----
echo.
echo    =========================================================
echo    [X] Python NO esta instalado en este equipo.
echo    =========================================================
echo    [RESULTADO] Python no encontrado en ningun nivel >> "%LOG_FILE%"
echo.

:: Intentar instalacion automatica con winget
echo    Intentando instalacion automatica...
echo    [AUTO] Intentando winget install... >> "%LOG_FILE%"
where winget >nul 2>&1
if !errorlevel! equ 0 (
    echo.
    echo    Se encontro winget (gestor de paquetes de Windows).
    echo    Se instalara Python 3.11 automaticamente.
    echo.
    echo    Presiona una tecla para instalar Python 3.11...
    pause >nul
    echo.
    echo    Instalando Python 3.11 (esto puede tardar unos minutos)...
    echo    [AUTO] Ejecutando: winget install Python.Python.3.11 >> "%LOG_FILE%"
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements 2>> "%LOG_FILE%"
    if !errorlevel! equ 0 (
        echo.
        echo    [OK] Python 3.11 instalado exitosamente.
        echo    [OK] winget instalo Python 3.11 >> "%LOG_FILE%"
        echo.
        echo    =========================================================
        echo    IMPORTANTE: Cierra esta ventana y ejecuta INSTALAR.bat
        echo    de nuevo para que Windows reconozca el nuevo Python.
        echo    =========================================================
        echo.
        pause
        exit /b 0
    ) else (
        echo    [X] winget fallo al instalar Python.
        echo    [ERROR] winget install fallo >> "%LOG_FILE%"
    )
) else (
    echo    [--] winget no disponible en este equipo.
    echo    [SKIP] winget no disponible >> "%LOG_FILE%"
)

:: Instrucciones manuales como ultimo recurso
echo.
echo    =========================================================
echo    INSTRUCCIONES PARA INSTALAR PYTHON MANUALMENTE:
echo    =========================================================
echo.
echo    1. Abre tu navegador y ve a:
echo       https://www.python.org/downloads/
echo.
echo    2. Descarga Python 3.11.x (recomendado)
echo.
echo    3. Al ejecutar el instalador, MARCA estas casillas:
echo       [X] "Add python.exe to PATH"  (MUY IMPORTANTE)
echo       [X] "Install py launcher"
echo.
echo    4. Haz clic en "Install Now"
echo.
echo    5. Cuando termine, CIERRA esta ventana y ejecuta
echo       INSTALAR.bat de nuevo.
echo.
echo    Si Python ya esta instalado pero no funciona:
echo    - Abre "Configuracion" de Windows
echo    - Busca "Administrar alias de ejecucion de aplicaciones"
echo    - DESACTIVA los alias de python.exe y python3.exe
echo.
pause
exit /b 1

:: ==============================================
:: PYTHON ENCONTRADO - Validaciones
:: ==============================================
:python_encontrado
echo.
echo    ^>^>^> Usando: %PYTHON_CMD% (version %PYTHON_VER%)
echo    [SELECCION] Comando final: %PYTHON_CMD% = %PYTHON_VER% >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 2: Validar version de Python
:: -----------------------------------------------
echo.
echo  [2/7] Validando version de Python...      [##........] 28%%
echo [PASO 2] Validando version %PYTHON_VER%... >> "%LOG_FILE%"

:: Extraer major.minor para validacion
for /f "tokens=1,2 delims=." %%a in ('echo !PYTHON_VER!') do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

set /a PY_MINOR_INT=!PY_MINOR!
set VERSION_OK=0
if "!PY_MAJOR!"=="3" (
    if !PY_MINOR_INT! geq 9 (
        if !PY_MINOR_INT! leq 12 (
            set VERSION_OK=1
        )
    )
)
if "!VERSION_OK!"=="1" goto :version_compatible

echo    [X] Version incompatible: Python %PYTHON_VER%
echo    [ERROR] Version %PYTHON_VER% fuera de rango 3.9-3.12 >> "%LOG_FILE%"
echo.
echo    DepthGuard requiere Python 3.9 a 3.12
echo    (mediapipe y dlib no soportan versiones fuera de este rango)
echo.
if !PY_MINOR_INT! gtr 12 (
    echo    Tu version (%PYTHON_VER%^) es demasiado nueva.
    echo    Instala Python 3.11 desde: https://www.python.org/downloads/release/python-3119/
) else (
    echo    Tu version (%PYTHON_VER%^) es demasiado vieja.
    echo    Instala Python 3.11 desde: https://www.python.org/downloads/
)
echo.
pause
exit /b 1

:version_compatible
echo    [OK] Version %PYTHON_VER% compatible (rango: 3.9 - 3.12)
echo    [OK] Version valida >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 3: Verificar pip y conectividad
:: -----------------------------------------------
echo.
echo  [3/7] Verificando pip y conectividad...   [###.......] 42%%
echo [PASO 3] Verificando pip y conectividad... >> "%LOG_FILE%"

:: Verificar pip
%PYTHON_CMD% -m pip --version >nul 2>&1
if !errorlevel! neq 0 (
    echo    [~] pip no disponible. Intentando instalar...
    echo    [WARN] pip no encontrado, instalando... >> "%LOG_FILE%"
    %PYTHON_CMD% -m ensurepip --default-pip 2>> "%LOG_FILE%"
    if !errorlevel! neq 0 (
        echo    [X] No se pudo instalar pip. La instalacion no puede continuar.
        echo    [ERROR] ensurepip fallo >> "%LOG_FILE%"
        pause
        exit /b 1
    )
    echo    [OK] pip instalado correctamente
    echo    [OK] pip instalado via ensurepip >> "%LOG_FILE%"
) else (
    echo    [OK] pip disponible
    echo    [OK] pip OK >> "%LOG_FILE%"
)

:: Verificar conectividad a internet
echo    Verificando conexion a internet...
ping -n 1 -w 3000 pypi.org >nul 2>&1
if !errorlevel! neq 0 (
    ping -n 1 -w 3000 google.com >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo    [!!] SIN CONEXION A INTERNET
        echo    [ERROR] Sin conexion a internet >> "%LOG_FILE%"
        echo.
        echo    No se pueden descargar las dependencias sin internet.
        echo    Conectate a una red Wi-Fi o Ethernet y ejecuta
        echo    INSTALAR.bat de nuevo.
        echo.
        pause
        exit /b 1
    )
)
echo    [OK] Conexion a internet verificada
echo    [OK] Internet OK >> "%LOG_FILE%"

:: -----------------------------------------------
:: PASO 4: Crear entorno virtual
:: -----------------------------------------------
echo.
echo  [4/7] Creando entorno virtual...          [####......] 57%%
echo [PASO 4] Creando entorno virtual... >> "%LOG_FILE%"

if not exist venv goto :crear_venv

REM Verificar que el venv no esta roto
venv\Scripts\python.exe --version >nul 2>&1
if !errorlevel! equ 0 (
    echo    [~] Ya existe un entorno virtual. Se usara el existente.
    echo    [SKIP] Entorno virtual ya existe >> "%LOG_FILE%"
    goto :venv_ok
)

echo    [~] Entorno virtual roto. Recreando...
echo    [WARN] venv roto, recreando >> "%LOG_FILE%"
rmdir /s /q venv 2>> "%LOG_FILE%"

:crear_venv
%PYTHON_CMD% -m venv venv 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] ERROR: No se pudo crear el entorno virtual.
    echo    [ERROR] Fallo al crear venv >> "%LOG_FILE%"
    pause
    exit /b 1
)
echo    [OK] Entorno virtual creado
echo    [OK] Entorno virtual creado >> "%LOG_FILE%"

:venv_ok

:: -----------------------------------------------
:: PASO 5: Activar entorno y actualizar pip
:: -----------------------------------------------
echo.
echo  [5/7] Activando entorno y actualizando... [######....] 71%%
echo [PASO 5] Activando entorno virtual... >> "%LOG_FILE%"
call venv\Scripts\activate.bat 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] ERROR: No se pudo activar el entorno virtual.
    echo    [ERROR] Fallo al activar venv >> "%LOG_FILE%"
    pause
    exit /b 1
)
echo    [OK] Entorno virtual activado
echo    [OK] Entorno virtual activado >> "%LOG_FILE%"

echo    Actualizando pip...
python -m pip install --upgrade pip --quiet 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [~] Hubo un problema actualizando pip. Revisa %LOG_FILE%.
) else (
    echo    [OK] pip actualizado
)

:: -----------------------------------------------
:: PASO 6: Instalar dependencias
:: -----------------------------------------------
echo.
echo  [6/7] Instalando dependencias...          [########..] 85%%
echo [PASO 6] Instalando dependencias... >> "%LOG_FILE%"

echo    ^> [6a] dlib (precompilado)...
python -m pip install dlib-bin --quiet 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [~] dlib-bin fallo. Intentando con dlib normal...
    python -m pip install dlib --quiet 2>> "%LOG_FILE%"
)
echo    ^> [6b] numpy...
python -m pip install "numpy<2" --quiet 2>> "%LOG_FILE%"
echo    ^> [6c] OpenCV...
python -m pip install opencv-python --quiet 2>> "%LOG_FILE%"
echo    ^> [6d] MediaPipe...
python -m pip install mediapipe --quiet 2>> "%LOG_FILE%"
echo    ^> [6e] face-recognition...
python -m pip install face-recognition --no-deps --quiet 2>> "%LOG_FILE%"
python -m pip install face_recognition_models click Pillow --quiet 2>> "%LOG_FILE%"
echo    ^> [6f] Supabase SDK...
python -m pip install supabase --quiet 2>> "%LOG_FILE%"
echo    ^> [6g] python-dotenv...
python -m pip install python-dotenv --quiet 2>> "%LOG_FILE%"
echo    ^> [6h] pyrealsense2 (opcional)...
python -m pip install pyrealsense2 --quiet 2>> "%LOG_FILE%"
echo    ^> [6i] aiortc + av (WebRTC streaming)...
python -m pip install aiortc av --quiet 2>> "%LOG_FILE%"
echo    [OK] Dependencias procesadas

:: -----------------------------------------------
:: PASO 7: Configurar .env + Verificacion Final
:: -----------------------------------------------
echo.
echo  [7/7] Configurando y verificando...       [##########] 100%%
if exist .env (
    echo    [~] Ya existe un archivo .env.
) else (
    if exist .env.example (
        copy .env.example .env >nul 2>> "%LOG_FILE%"
        echo    [OK] Archivo .env creado.
    )
)

echo.
echo -------------------------------------------------
echo   Verificando modulos criticos...
echo -------------------------------------------------
python -c "import cv2" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import mediapipe" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import face_recognition" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import numpy" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import supabase" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import dlib" 2>> "%LOG_FILE%" || set INSTALL_OK=0
python -c "import aiortc" 2>> "%LOG_FILE%" || echo    [~] aiortc NO disponible (fallback)

echo.
if "!INSTALL_OK!"=="1" (
    echo =========================================================
    echo   INSTALACION COMPLETADA EXITOSAMENTE
    echo =========================================================
) else (
    echo =========================================================
    echo   INSTALACION CON PROBLEMAS
    echo =========================================================
)
echo   Log guardado en: %LOG_FILE%
pause
endlocal
