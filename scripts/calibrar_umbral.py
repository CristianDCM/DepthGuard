"""
Calibra TOLERANCIA_FACIAL (o TOLERANCIA_FACIAL_ONNX) con los usuarios ya
registrados.

    python scripts/calibrar_umbral.py

Por que hace falta
------------------
El umbral decide quien entra. Si es demasiado alto se deja pasar a un
desconocido; si es demasiado bajo no reconoce al usuario legitimo. El valor por
defecto es una eleccion razonable tomada de la literatura, NO una medida de tus
rostros, de tu camara y de tu iluminacion.

Que hace
--------
Compara todas las plantillas guardadas entre si y separa las distancias en dos
grupos:

  * MISMA persona (plantillas del mismo usuario en distintos angulos).
    Cuanto mas lejos, mas facil es NO reconocer a alguien que si deberia pasar.

  * PERSONAS DISTINTAS. Cuanto mas cerca, mas facil es confundir a dos.

El umbral debe quedar entre el maximo del primer grupo y el minimo del segundo.
Si esos dos numeros se cruzan, no hay ningun umbral que acierte siempre y el
problema no se arregla moviendolo: hacen falta mejores plantillas (volver a
registrar con buena luz y poses bien diferenciadas).

AVISO: con pocos usuarios esto es una orientacion, no una garantia. Dos
usuarios dan una sola comparacion entre personas distintas.
"""

import os
import sys
import json
import itertools

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def cargar_usuarios():
    from backend.supabase_cliente import obtener_cliente

    supabase = obtener_cliente()
    resp = supabase.table("usuarios").select(
        "id, nombre, embeddings_json, activo"
    ).eq("activo", True).execute()

    usuarios = []
    for fila in resp.data or []:
        emb = fila.get("embeddings_json")
        if not emb:
            continue
        lista = emb if isinstance(emb, list) else json.loads(emb)
        if lista:
            usuarios.append((fila["nombre"], [np.asarray(e, dtype=np.float64)
                                              for e in lista]))
    return usuarios


def main():
    from config.settings import (
        MOTOR_EMBEDDING, TOLERANCIA_FACIAL, TOLERANCIA_FACIAL_ONNX,
        MARGEN_IDENTIDAD, MARGEN_IDENTIDAD_ONNX,
    )

    es_onnx = MOTOR_EMBEDDING == "onnx"
    umbral_actual = TOLERANCIA_FACIAL_ONNX if es_onnx else TOLERANCIA_FACIAL
    margen_actual = MARGEN_IDENTIDAD_ONNX if es_onnx else MARGEN_IDENTIDAD
    esperadas = 512 if es_onnx else 128
    variable = "TOLERANCIA_FACIAL_ONNX" if es_onnx else "TOLERANCIA_FACIAL"

    print("=" * 66)
    print(" CALIBRACION DEL UMBRAL")
    print("=" * 66)
    print(f"\nMotor activo    : {MOTOR_EMBEDDING} ({esperadas} dimensiones)")
    print(f"Umbral actual   : {variable} = {umbral_actual}")
    print(f"Margen actual   : {margen_actual}")

    try:
        usuarios = cargar_usuarios()
    except Exception as e:
        print(f"\nNo pude leer los usuarios: {type(e).__name__}: {e}")
        return 1

    if not usuarios:
        print("\nNo hay usuarios activos con plantillas.")
        return 1

    # Descartar plantillas del otro motor antes de medir: mezclarlas daria
    # numeros sin sentido y una recomendacion peor que no dar ninguna.
    limpios, descartadas = [], 0
    for nombre, plantillas in usuarios:
        buenas = [p for p in plantillas if p.shape[-1] == esperadas]
        descartadas += len(plantillas) - len(buenas)
        if buenas:
            limpios.append((nombre, buenas))

    print(f"\nUsuarios        : {len(limpios)}")
    print(f"Plantillas      : {sum(len(p) for _, p in limpios)}")
    if descartadas:
        print(f"  {descartadas} descartadas por ser de otro motor "
              f"(se esperaban {esperadas} dimensiones)")
    if not limpios:
        print(f"\nNinguna plantilla sirve para el motor {MOTOR_EMBEDDING}.")
        print("Hay que volver a registrar a los usuarios.")
        return 1

    # --- Distancias dentro de cada persona ---
    intra = []
    for nombre, plantillas in limpios:
        for a, b in itertools.combinations(plantillas, 2):
            intra.append((float(np.linalg.norm(a - b)), nombre))

    # --- Distancias entre personas distintas ---
    inter = []
    for (n1, p1), (n2, p2) in itertools.combinations(limpios, 2):
        for a in p1:
            for b in p2:
                inter.append((float(np.linalg.norm(a - b)), f"{n1} vs {n2}"))

    print("\n" + "-" * 66)
    if intra:
        d = sorted(x[0] for x in intra)
        peor = max(intra)
        print(f"MISMA persona   ({len(intra)} pares)")
        print(f"  minima {d[0]:.3f}   mediana {d[len(d)//2]:.3f}   "
              f"MAXIMA {d[-1]:.3f}")
        print(f"  el par mas lejano es de: {peor[1]}")
    else:
        print("MISMA persona   : sin pares (cada usuario tiene 1 plantilla)")

    if inter:
        d = sorted(x[0] for x in inter)
        mejor = min(inter)
        print(f"\nPersonas DISTINTAS ({len(inter)} pares)")
        print(f"  MINIMA {d[0]:.3f}   mediana {d[len(d)//2]:.3f}   "
              f"maxima {d[-1]:.3f}")
        print(f"  el par mas cercano es: {mejor[1]}")
    else:
        print("\nPersonas DISTINTAS: sin pares (hace falta mas de un usuario)")

    print("\n" + "=" * 66)
    print(" RECOMENDACION")
    print("=" * 66)

    max_intra = max((x[0] for x in intra), default=None)
    min_inter = min((x[0] for x in inter), default=None)

    if max_intra is None or min_inter is None:
        print("\nNo hay datos suficientes para recomendar un umbral.")
        print("Hacen falta al menos 2 usuarios con 2 plantillas cada uno.")
        return 0

    if max_intra >= min_inter:
        print(f"\n  LOS GRUPOS SE CRUZAN: la mayor distancia dentro de una")
        print(f"  persona ({max_intra:.3f}) supera la menor entre personas")
        print(f"  distintas ({min_inter:.3f}).")
        print( "\n  Ningun umbral acierta siempre, y moverlo solo cambia que")
        print( "  tipo de error cometes. Esto se arregla con mejores")
        print( "  plantillas: volver a registrar con buena luz, rostro nitido")
        print( "  y poses bien diferenciadas.")
        print(f"\n  Mientras tanto, lo mas seguro para control de acceso es")
        print(f"  quedarse por debajo de {min_inter:.3f} (prioriza no dejar")
        print( "  pasar a un desconocido, aunque a veces no te reconozca).")
        return 0

    sugerido = (max_intra + min_inter) / 2
    print(f"\n  Hay separacion limpia:")
    print(f"    misma persona, como mucho : {max_intra:.3f}")
    print(f"    distintas, como poco      : {min_inter:.3f}")
    print(f"    hueco                     : {min_inter - max_intra:.3f}")
    print(f"\n  Umbral sugerido (punto medio): {sugerido:.3f}")
    print(f"  En tu .env:\n      {variable}={sugerido:.3f}")

    if umbral_actual > min_inter:
        print(f"\n  ATENCION: el umbral actual ({umbral_actual}) esta POR ENCIMA")
        print(f"  de la menor distancia entre personas distintas ({min_inter:.3f}).")
        print( "  Tal como esta, el sistema puede confundir a dos usuarios.")
    elif umbral_actual < max_intra:
        print(f"\n  ATENCION: el umbral actual ({umbral_actual}) esta POR DEBAJO")
        print(f"  de la mayor distancia dentro de una persona ({max_intra:.3f}).")
        print( "  Tal como esta, el sistema puede no reconocer a un usuario")
        print( "  legitimo segun el angulo en que se ponga.")
    else:
        print(f"\n  El umbral actual ({umbral_actual}) cae dentro del hueco: bien.")

    print("\n  Recuerda: con pocos usuarios esto orienta, no garantiza.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
