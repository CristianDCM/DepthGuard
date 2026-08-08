@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
title DepthGuard - Sistema Activo
color 0A

set LOG_FILE=runtime_log.txt
set PYTHON_CMD=

:: Inicializar log
echo ========================================================= > "%LOG_FILE%"
echo   LOG DE EJECUCION DEPTHGUARD >> "%LOG_FILE%"
echo   Fecha: %date% %time% >> "%LOG_FILE%"
echo ========================================================= >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo.
echo =========================================================
echo   DEPTHGUARD
echo   Sistema de Control de Acceso Biometrico 3D
echo =========================================================
echo.

:: -----------------------------------------------
:: PASO 1: Detectar Python (misma cascada que INSTALAR.bat)
:: -----------------------------------------------
echo  [1/3] Detectando Python...                [###.......] 33%%
echo [PASO 1] Detectando Python... >> "%LOG_FILE%"

:: Nivel 1: py launcher
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py -3"
        for /f "tokens=2" %%i in ('py -3 --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Python Launcher: Python !PYTHON_VER!
        echo    [OK] py -3 = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_ok
    )
)

:: Nivel 2: python en PATH (sin Windows Store)
where python >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=*" %%p in ('where python 2^>nul') do (
        set "PYTHON_LOCATION=%%p"
        goto :check_store
    )
    :check_store
    echo !PYTHON_LOCATION! | findstr /i "WindowsApps" >nul 2>&1
    if !errorlevel! neq 0 (
        python -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=python"
            for /f "tokens=2" %%i in ('python --version 2^>^&1') do set "PYTHON_VER=%%i"
            echo    [OK] Python en PATH: Python !PYTHON_VER!
            echo    [OK] python = Python !PYTHON_VER! >> "%LOG_FILE%"
            goto :python_ok
        )
    )
)

:: Nivel 3: python3
where python3 >nul 2>&1
if !errorlevel! equ 0 (
    python3 -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python3"
        for /f "tokens=2" %%i in ('python3 --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] python3: Python !PYTHON_VER!
        echo    [OK] python3 = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_ok
    )
)

:: Nivel 4: Buscar en rutas comunes
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%d\python.exe" (
        set "PYTHON_CMD=%%d\python.exe"
        for /f "tokens=2" %%v in ('"%%d\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%v"
        echo    [OK] Encontrado: %%d
        echo    [OK] "%%d\python.exe" = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_ok
    )
)

for %%v in (313 312 311 310 39) do (
    if exist "C:\Python%%v\python.exe" (
        set "PYTHON_CMD=C:\Python%%v\python.exe"
        for /f "tokens=2" %%i in ('"C:\Python%%v\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Encontrado: C:\Python%%v\
        echo    [OK] C:\Python%%v\python.exe = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_ok
    )
)

:: Nivel 5: Registro de Windows
for /f "tokens=*" %%k in ('reg query "HKCU\Software\Python\PythonCore" /s /v InstallPath 2^>nul ^| findstr /i "InstallPath"') do (
    for /f "tokens=2,*" %%a in ("%%k") do set "REG_PYTHON_PATH=%%b"
)
if defined REG_PYTHON_PATH (
    if exist "!REG_PYTHON_PATH!\python.exe" (
        set "PYTHON_CMD=!REG_PYTHON_PATH!\python.exe"
        for /f "tokens=2" %%i in ('"!REG_PYTHON_PATH!\python.exe" --version 2^>^&1') do set "PYTHON_VER=%%i"
        echo    [OK] Registro HKCU: !REG_PYTHON_PATH!
        echo    [OK] HKCU registry = Python !PYTHON_VER! >> "%LOG_FILE%"
        goto :python_ok
    )
)

:: Python no encontrado
echo    [X] ERROR: Python no encontrado en este equipo.
echo    [ERROR] Python no encontrado >> "%LOG_FILE%"
echo.
echo    Ejecuta primero: INSTALAR.bat
echo.
pause
exit /b 1

:python_ok

:: -----------------------------------------------
:: PASO 2: Verificar entorno virtual
:: -----------------------------------------------
echo  [2/3] Verificando entorno virtual...      [######....] 66%%
echo [PASO 2] Verificando entorno virtual... >> "%LOG_FILE%"
if not exist venv\Scripts\activate.bat (
    echo    [X] ERROR: No se encontro el entorno virtual.
    echo [ERROR] venv no encontrado >> "%LOG_FILE%"
    echo.
    echo    Ejecuta primero: INSTALAR.bat
    echo.
    pause
    exit /b 1
)

REM Verificar que el venv no esta roto (ruta movida/renombrada)
venv\Scripts\python.exe --version >nul 2>&1
if !errorlevel! equ 0 (
    echo    [OK] Entorno virtual OK
    echo    [OK] Entorno virtual encontrado >> "%LOG_FILE%"
    goto :iniciar_venv_ok
)

echo    [~] Entorno virtual roto (la carpeta fue movida/renombrada). Reparando...
echo    [WARN] venv roto, recreando >> "%LOG_FILE%"
rmdir /s /q venv 2>> "%LOG_FILE%"
%PYTHON_CMD% -m venv venv 2>> "%LOG_FILE%"
if !errorlevel! neq 0 (
    echo    [X] ERROR: No se pudo recrear el entorno virtual.
    echo [ERROR] Fallo al recrear venv >> "%LOG_FILE%"
    pause
    exit /b 1
)
echo    [OK] Entorno virtual recreado. Reinstalando dependencias...
echo    [OK] venv recreado >> "%LOG_FILE%"
call venv\Scripts\activate.bat 2>> "%LOG_FILE%"
python -m pip install --upgrade pip --quiet 2>> "%LOG_FILE%"
python -m pip install -r requirements.txt --quiet 2>> "%LOG_FILE%"
echo    [OK] Dependencias reinstaladas
echo    [OK] Dependencias reinstaladas >> "%LOG_FILE%"

:iniciar_venv_ok

:: -----------------------------------------------
:: PASO 3: Verificar .env y arrancar
:: -----------------------------------------------
echo  [3/3] Iniciando sistema...                [##########] 100%%
echo [PASO 3] Verificando .env e iniciando... >> "%LOG_FILE%"

if not exist .env (
    echo    [~] No se encontro archivo .env
    echo    [WARN] .env no encontrado >> "%LOG_FILE%"
    echo    Creando uno desde .env.example...
    if exist .env.example (
        copy .env.example .env >nul 2>> "%LOG_FILE%"
        echo    [OK] .env creado. Edita las credenciales si es necesario.
        echo    [OK] .env creado desde .env.example >> "%LOG_FILE%"
    ) else (
        echo    [X] No se encontro .env.example
        echo    [ERROR] .env.example no encontrado >> "%LOG_FILE%"
        echo    El sistema usara valores por defecto.
    )
    echo.
) else (
    echo    [OK] Archivo .env encontrado
    echo    [OK] .env existe >> "%LOG_FILE%"
)

:: Activar venv e iniciar
call venv\Scripts\activate.bat 2>> "%LOG_FILE%"
echo    [OK] Entorno virtual activado
echo    [OK] Entorno activado >> "%LOG_FILE%"

echo.
echo -------------------------------------------------
echo   DepthGuard esta iniciando...
echo   Python: %PYTHON_CMD% (%PYTHON_VER%)
echo -------------------------------------------------
echo.
echo   Presiona 'q' en la ventana de la camara para cerrar.
echo   Presiona Ctrl+C aqui para detener el sistema.
echo.
echo [INICIO] Ejecutando iniciar.py... >> "%LOG_FILE%"

python iniciar.py 2>> "%LOG_FILE%"

set EXIT_CODE=%errorlevel%
echo [FIN] iniciar.py termino con codigo: %EXIT_CODE% >> "%LOG_FILE%"

:: -----------------------------------------------
:: Al salir
:: -----------------------------------------------
echo.
if %EXIT_CODE% neq 0 (
    echo =========================================================
    echo   DepthGuard termino con errores. Revisa: %LOG_FILE%
    echo =========================================================
    echo    [RESULTADO] Salida con error (codigo %EXIT_CODE%) >> "%LOG_FILE%"
) else (
    echo =========================================================
    echo   DepthGuard detenido correctamente.
    echo =========================================================
    echo    [RESULTADO] Salida limpia >> "%LOG_FILE%"
)
echo.
echo   Log guardado en: %LOG_FILE%
echo.
pause
endlocal
