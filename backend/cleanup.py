"""
Limpieza automática de datos antiguos.

Ejecuta cada 24 horas (configurable) la eliminación de:
  - Fotos de eventos en Supabase Storage (bucket "capturas")
  - Registros del historial en la tabla "historial"

NO toca: usuarios, embeddings, fotos de perfil, estado_sistema, comandos_edge.

Política de retención configurable vía DIAS_RETENCION en .env (default: 30 días).
"""

import time
import datetime
import traceback

from backend.supabase_cliente import obtener_cliente
from config.settings import DIAS_RETENCION


def _extraer_nombre_archivo(foto_url: str) -> str | None:
    """
    Extrae el nombre del archivo de una URL de Supabase Storage.
    Ejemplo: https://xxx.supabase.co/storage/v1/object/public/capturas/evento_abc.jpg
    Retorna: "evento_abc.jpg"
    """
    if not foto_url:
        return None

    try:
        # La URL de Supabase Storage tiene el formato:
        # .../storage/v1/object/public/{bucket}/{nombre_archivo}
        partes = foto_url.split("/capturas/")
        if len(partes) >= 2:
            return partes[-1].split("?")[0]  # Quitar query params si los hay
    except Exception:
        pass

    return None


def _ejecutar_limpieza():
    """
    Ejecuta una ronda de limpieza.
    Retorna (registros_eliminados, fotos_eliminadas).
    """
    supabase = obtener_cliente()
    fecha_limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_RETENCION)
    fecha_iso = fecha_limite.isoformat()

    print(f"🧹 Limpieza: eliminando datos anteriores a {fecha_limite.strftime('%Y-%m-%d %H:%M')} ({DIAS_RETENCION} días)")

    # 1. Obtener registros antiguos (en lotes de 100 para no sobrecargar)
    registros_eliminados = 0
    fotos_eliminadas = 0

    try:
        resultado = supabase.table("historial") \
            .select("id, foto_url") \
            .lt("timestamp", fecha_iso) \
            .limit(500) \
            .execute()

        registros = resultado.data if resultado.data else []

        if not registros:
            print("   ✅ No hay registros antiguos para limpiar")
            return 0, 0

        print(f"   📋 {len(registros)} registros encontrados para eliminar")

        # 2. Eliminar fotos del Storage (en lotes)
        archivos_a_eliminar = []
        for reg in registros:
            nombre = _extraer_nombre_archivo(reg.get("foto_url"))
            if nombre:
                archivos_a_eliminar.append(nombre)

        if archivos_a_eliminar:
            # Supabase Storage permite eliminar en lotes
            try:
                # Eliminar en lotes de 50
                for i in range(0, len(archivos_a_eliminar), 50):
                    lote = archivos_a_eliminar[i:i + 50]
                    supabase.storage.from_("capturas").remove(lote)
                    fotos_eliminadas += len(lote)
            except Exception as e:
                print(f"   ⚠️ Error eliminando fotos del Storage: {e}")
                # Continuar con la eliminación de registros aunque falle Storage

        # 3. Eliminar registros de la BD
        ids_a_eliminar = [reg["id"] for reg in registros]

        # Eliminar en lotes de 50
        for i in range(0, len(ids_a_eliminar), 50):
            lote_ids = ids_a_eliminar[i:i + 50]
            for reg_id in lote_ids:
                try:
                    supabase.table("historial").delete().eq("id", reg_id).execute()
                    registros_eliminados += 1
                except Exception:
                    pass  # Si falla uno, continuar con los demás

        return registros_eliminados, fotos_eliminadas

    except Exception as e:
        print(f"   ❌ Error durante la limpieza: {e}")
        traceback.print_exc()
        return registros_eliminados, fotos_eliminadas


def iniciar_cleanup(intervalo_horas: int = 24):
    """
    Hilo daemon que ejecuta limpieza periódica.
    Se espera 60 segundos al arrancar para no interferir con la inicialización del sistema.
    """
    print("🧹 Cleanup: iniciando (primera ejecución en 60s)")

    # Esperar al arranque completo del sistema
    time.sleep(60)

    while True:
        try:
            inicio = time.time()
            registros, fotos = _ejecutar_limpieza()
            duracion = round(time.time() - inicio, 1)

            if registros > 0 or fotos > 0:
                print(f"   🧹 Limpieza completada en {duracion}s:")
                print(f"      📋 {registros} registros del historial eliminados")
                print(f"      📸 {fotos} fotos del Storage eliminadas")
            else:
                print(f"   🧹 Limpieza completada en {duracion}s (nada que limpiar)")

        except Exception as e:
            print(f"   ❌ Cleanup: error inesperado: {e}")
            traceback.print_exc()

        # Esperar hasta la próxima ejecución
        print(f"   ⏰ Próxima limpieza en {intervalo_horas}h")
        time.sleep(intervalo_horas * 3600)
