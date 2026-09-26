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
| 2 | Versiones congeladas | `empaquetado/requirements-build.txt` con las versiones exactas del equipo que funciona + `empaquetado/verificar_entorno.py` | Instalación limpia con el lock → verificador OK → suite completa en verde con esas versiones | Hecha |
| 3 | Ejecutable (PyInstaller) | `DepthGuard.exe` + modo `--autoprueba` (carga todas las librerías y modelos y sale) + build en GitHub Actions (Windows) | La autoprueba pasa en CI; luego se prueba en el equipo con la cámara real | En CI |
| 4 | Instalador (Inno Setup) | `DepthGuard-Setup.exe`: instala en Program Files y pide URL + clave de Supabase y modo de cámara | Instalar, actualizar y desinstalar en un Windows limpio | Pendiente |
| 5 | Arranque automático | Arranca con Windows y se reinicia si se cae | Reiniciar el equipo; matar el proceso | Pendiente |
| 6 | Publicación | GitHub Release versionada con el instalador; README actualizado | Descargar e instalar desde la Release | Pendiente |

### Fase 2: qué se decidió y por qué

- **El lock sale del equipo que funciona, no de `requirements.txt`.** Ese
  equipo ya no coincide con el repo (numpy 2.4.6 frente a 1.24.4, OpenCV 5
  frente a 4.8, supabase 2.31 frente a 2.15). Todas las versiones tienen
  paquete precompilado para Windows + Python 3.11 (comprobado).
- **Se instala con `--no-deps`.** Sin esa opción, pip intenta compilar dlib
  (`face-recognition` pide `dlib` y `dlib-bin` no cuenta) y mete un segundo OpenCV.
- **Un solo OpenCV: `opencv-contrib-python`.** El equipo tenía los dos, y ambos
  escriben el mismo `cv2/cv2.pyd`. mediapipe exige el contrib, que además
  incluye todo lo del otro.
- **`setuptools==80.10.2` fijado.** `pip freeze` nunca lo lista, pero
  `face_recognition_models` necesita `pkg_resources`, que desapareció en
  setuptools 82. Con una versión nueva, `face_recognition` **no lanza un
  error: llama a `quit()` y el proceso termina con código 0**, como si todo
  hubiera ido bien. El verificador trata ese caso como fallo, y un test impide
  subir setuptools en el lock.

### Fase 3: cómo se construye

Todo lo hace `.github/workflows/build-windows.yml` en un Windows de GitHub.
Cada paso es una puerta: si falla, no se publica nada.

1. Python **3.11.9** exacto e instalación con `--no-deps` de
   `requirements-build.txt` y `requirements-pyinstaller.txt`.
2. `empaquetado/verificar_entorno.py`.
3. La suite completa (`python -m unittest discover -s tests -t .`).
4. `pyinstaller empaquetado/DepthGuard.spec`.
5. `DepthGuard.exe --autoprueba`, ejecutado desde una ruta con espacios y desde
   otro directorio de trabajo.
6. Se sube `dist/DepthGuard/` como artefacto (14 días).

Para construirlo en tu propio Windows, los mismos comandos en un venv limpio
con Python 3.11.9.

La autoprueba (`autoprueba.py`) hace trabajar una vez cada pieza nativa sin
cámara, sin `.env` y sin Supabase: carpeta de datos, OpenCV, Face Mesh,
embedding de dlib, codificadores VP8/H264, SDK de RealSense, onnxruntime,
SDK de Supabase y el pipeline. Ya demostró su valor: la primera versión del
`.spec` excluía `mediapipe.tasks.python.genai` y rompía Face Mesh, y fue la
autoprueba la que lo detectó.

Decisiones del `.spec`:
- **Se copian a mano** los modelos de mediapipe, los `.dat` de dlib y las
  librerías de pyrealsense2: no hay hook que lo haga.
- **Se excluyen jax, jaxlib y scipy** (unos 490 MB). Solo los usa el conversor
  "genai" de mediapipe, nunca Face Mesh.
- **Sin UPX** (falsos positivos de antivirus) y **con consola** por ahora.

Resultado: unos 700 MB en onedir, medido en el build de Linux; el de Windows
aparece en el resumen de cada build.

### Riesgos abiertos para la fase 4

- **Visual C++ Redistributable.** Los runners de GitHub lo traen instalado, así
  que la autoprueba pasaría aunque el ejecutable lo necesite. Un Windows limpio
  puede no tenerlo. El instalador debe incluirlo o comprobarlo, y la prueba
  de la fase 4 tiene que hacerse en un Windows limpio.
- **`INSTALAR.bat` y `requirements.txt` desactualizados** respecto al equipo
  que funciona. No se tocan hasta la fase 6, para no cambiar nada a quien
  instala sin empaquetar.

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
