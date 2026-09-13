"""
Descarga el modelo ONNX de reconocimiento facial.

    python scripts/descargar_modelo.py

Deja w600k_mbf.onnx (MobileFaceNet entrenado con ArcFace sobre WebFace600K,
14 MB) en scripts/_modelos/, que es donde lo busca RUTA_MODELO_ONNX.

El modelo NO va en el repositorio: son 14 MB de binario que no aportan nada al
control de versiones y que cualquiera puede volver a bajar.
"""

import os
import sys
import zipfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Varias fuentes porque los enlaces de modelos se mueven con el tiempo.
# Lo descargado se valida antes de darlo por bueno.
FUENTES = [
    ("https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
     "zip", "w600k_mbf.onnx"),
    ("https://huggingface.co/immich-app/antelopev2/resolve/main/buffalo_s.zip",
     "zip", "w600k_mbf.onnx"),
]


def main():
    from config.settings import RUTA_MODELO_ONNX

    destino = RUTA_MODELO_ONNX
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    if os.path.isfile(destino):
        print(f"Ya esta descargado: {destino}")
        print(f"  ({os.path.getsize(destino)/1e6:.0f} MB)")
        return 0

    tmp = destino + ".tmp"
    for url, tipo, dentro in FUENTES:
        print(f"Descargando de {url.split('/')[2]} ...")
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                f.write(r.read())

            if tipo == "zip":
                with zipfile.ZipFile(tmp) as z:
                    nombre = next((n for n in z.namelist() if n.endswith(dentro)), None)
                    if nombre is None:
                        print(f"  el zip no contiene {dentro}")
                        continue
                    with z.open(nombre) as origen, open(destino, "wb") as f:
                        f.write(origen.read())
            else:
                os.replace(tmp, destino)

            # Validar que de verdad carga antes de declararlo descargado: un
            # fichero corrupto o una pagina de error HTML pesan bytes igual.
            try:
                import onnxruntime as ort
                ses = ort.InferenceSession(
                    destino, providers=["CPUExecutionProvider"])
                forma = ses.get_inputs()[0].shape
                salida = ses.get_outputs()[0].shape
                print(f"\nListo: {destino}")
                print(f"  {os.path.getsize(destino)/1e6:.0f} MB")
                print(f"  entrada {forma}  ->  salida {salida}")
            except ImportError:
                print(f"\nDescargado en {destino}, pero no puedo validarlo:")
                print("  falta onnxruntime (pip install onnxruntime)")
            return 0

        except Exception as e:
            print(f"  fallo: {type(e).__name__}: {e}")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    print("\nNo se pudo descargar automaticamente.")
    print("Baja 'buffalo_s.zip' de InsightFace a mano, saca w600k_mbf.onnx y")
    print(f"deja el fichero en:\n  {destino}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
