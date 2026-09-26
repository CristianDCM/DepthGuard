# Empaquetado de DepthGuard — plan por fases

Objetivo: que quien instala DepthGuard reciba **un solo `DepthGuard-Setup.exe`**,
sin Python, sin consola y sin ver el código, y que el edge arranque solo.

Decisión: **PyInstaller en modo *onedir* + instalador Inno Setup**. Se descartan
*onefile* (arranque lento, más falsos positivos de antivirus) y Docker (acceso
USB a la cámara/RealSense en Windows).

## Reglas para que no falle para nadie

1. **Todo en una rama aparte.** `main` no cambia hasta que una fase esté validada.
2. **Sin empaquetar, nada cambia.** `python iniciar.py`, `INSTALAR.bat` e
   `INICIAR.bat` siguen funcionando igual en todas las fases. Hay tests que lo
   comprueban (`tests/test_rutas.py`).
3. **Cada fase se valida antes de pasar a la siguiente.** Tests en verde + la
   prueba manual que indica la fase.
4. **Versiones idénticas a las probadas.** El ejecutable se construye con las
   versiones exactas del equipo donde DepthGuard ya funciona, no con "la última".
5. **Los datos del cliente nunca se pisan.** Actualizar o desinstalar no borra
   el `.env` ni las capturas sin preguntar.

## Fases

| # | Fase | Resultado | Cómo se valida | Estado |
|---|------|-----------|----------------|--------|
| 1 | Rutas preparadas para empaquetar | `config/rutas.py`: sin empaquetar todo sigue en la raíz del repo; empaquetado, los datos van a `%PROGRAMDATA%\DepthGuard` | Tests + arrancar con `python iniciar.py` como siempre | Hecha |
| 2 | Versiones congeladas | `empaquetado/requirements-build.txt` con las versiones exactas del equipo que funciona | `pip freeze` del venv que funciona hoy | Pendiente |
| 3 | Ejecutable (PyInstaller) | `DepthGuard.exe` + modo `--autoprueba` (carga todas las librerías y modelos y sale) + build en GitHub Actions (Windows) | La autoprueba pasa en CI; luego se prueba en el equipo con la cámara real | Pendiente |
| 4 | Instalador (Inno Setup) | `DepthGuard-Setup.exe`: instala en Program Files y pide URL + clave de Supabase y modo de cámara | Instalar, actualizar y desinstalar en un Windows limpio | Pendiente |
| 5 | Arranque automático | Arranca con Windows y se reinicia si se cae | Reiniciar el equipo; matar el proceso | Pendiente |
| 6 | Publicación | GitHub Release versionada con el instalador; README actualizado | Descargar e instalar desde la Release | Pendiente |

### Riesgos ya detectados para la fase 2

- **Dos OpenCV a la vez.** Instalando `requirements.txt` en limpio, mediapipe
  arrastra `opencv-contrib-python` 4.11 además del `opencv-python` 4.8 fijado.
  Los dos escriben el mismo módulo `cv2`, y cuál gana depende del orden de
  instalación. En el build tiene que quedar uno solo.
- **`face-recognition` intenta compilar dlib.** Declara `dlib` como dependencia
  y `dlib-bin` no cuenta como tal, así que pip intenta compilarlo desde el
  código fuente. `INSTALAR.bat` lo evita con `--no-deps`, y el build debe
  hacer lo mismo.
- **`INSTALAR.bat` instala versiones sin fijar** (`pip install mediapipe`...),
  distintas de las de `requirements.txt`. No se toca hasta la fase 6.

## Dónde queda cada cosa una vez instalado

| Qué | Dónde | Por qué |
|-----|-------|---------|
| Programa | `C:\Program Files\DepthGuard\` | Solo lectura; lo reemplaza cada actualización |
| `.env`, capturas, modelos | `C:\ProgramData\DepthGuard\` | Escribible sin ser administrador y común a todos los usuarios; sobrevive a las actualizaciones |

`DEPTHGUARD_DATOS` fuerza otra carpeta de datos (pruebas o varias instalaciones).

## Lo que el empaquetado NO hace

- **No protege el código.** El `.exe` de PyInstaller se puede descompilar. Si
  hace falta de verdad, se evalúa Nuitka como fase aparte.
- **No protege el `.env`.** Sigue siendo legible en el equipo. Por eso el edge
  debe usar `SUPABASE_EDGE_KEY` (restringida por RLS) y nunca la `service_role`.
- **Sin firma de código, Windows SmartScreen avisa** al instalar ("editor
  desconocido"). Evitarlo requiere un certificado de firma de pago.
