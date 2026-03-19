@echo off
echo ==========================================
echo   DepthGuard - Tunel Ngrok
echo ==========================================

for /f "tokens=2 delims==" %%a in ('findstr "NGROK_DOMAIN" ..\.env') do set DOMAIN=%%a

echo Dominio: %DOMAIN%
ngrok http --domain=%DOMAIN% 8000

pause
