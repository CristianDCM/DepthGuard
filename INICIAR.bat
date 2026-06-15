@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
title DepthGuard - Sistema Activo
color 0A

set LOG_FILE=runtime_log.txt

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
:: PASO 1: Verificar entorno virtual
:: -----------------------------------------------
echo  [1/3] Verificando entorno virtual...     [###.......] 33%%
echo [PASO 1] Verificando entorno virtual... >> "%LOG_FILE%"
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
python -m venv venv 2>> "%LOG_FILE%"
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
:: PASO 2: Verificar .env
:: -----------------------------------------------
echo  [2/3] Verificando archivo .env...        [######....] 66%%
echo [PASO 2] Verificando .env... >> "%LOG_FILE%"
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

:: -----------------------------------------------
:: PASO 3: Activar entorno e iniciar
:: -----------------------------------------------
echo  [3/3] Iniciando sistema...               [##########] 100%%
echo [PASO 3] Activando venv e iniciando... >> "%LOG_FILE%"
echo.
call venv\Scripts\activate.bat 2>> "%LOG_FILE%"
echo    [OK] Entorno virtual activado
echo    [OK] Entorno activado >> "%LOG_FILE%"

echo.
echo -------------------------------------------------
echo   DepthGuard esta iniciando...
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
