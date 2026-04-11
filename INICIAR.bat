@echo off
chcp 65001 >nul
title DepthGuard - Sistema Activo
color 0A

echo.
echo =========================================================
echo   🛡️  DEPTHGUARD
echo   Sistema de Control de Acceso Biometrico 3D
echo =========================================================
echo.

:: ─────────────────────────────────────────────
:: Verificar que el entorno virtual existe
:: ─────────────────────────────────────────────
if not exist venv\Scripts\activate.bat (
    echo ❌ ERROR: No se encontro el entorno virtual.
    echo.
    echo    Ejecuta primero: INSTALAR.bat
    echo.
    pause
    exit /b 1
)

:: ─────────────────────────────────────────────
:: Verificar que .env existe
:: ─────────────────────────────────────────────
if not exist .env (
    echo ⚠️  No se encontro archivo .env
    echo    Creando uno desde .env.example...
    if exist .env.example (
        copy .env.example .env >nul
        echo    ✅ .env creado. Edita las credenciales si es necesario.
    ) else (
        echo    ❌ No se encontro .env.example
        echo    El sistema usara valores por defecto.
    )
    echo.
)

:: ─────────────────────────────────────────────
:: Activar entorno e iniciar
:: ─────────────────────────────────────────────
echo Activando entorno virtual...
call venv\Scripts\activate.bat

echo Iniciando DepthGuard...
echo.
echo   Presiona 'q' en la ventana de la camara para cerrar.
echo   Presiona Ctrl+C aqui para detener el servidor.
echo.

python iniciar.py

:: ─────────────────────────────────────────────
:: Al salir
:: ─────────────────────────────────────────────
echo.
echo =========================================================
echo   DepthGuard detenido.
echo =========================================================
echo.
pause
