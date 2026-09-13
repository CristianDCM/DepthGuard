"""
Acceso a Supabase Storage para las capturas (hallazgo C5).

EL PROBLEMA
-----------
El bucket "capturas" es publico y el codigo usaba get_public_url(). Las fotos
faciales de cada evento de acceso y el frame de preview en vivo quedaban en
URLs SIN AUTENTICACION Y SIN CADUCIDAD. El preview, ademas, en una ruta fija y
adivinable (live_preview.jpg), o sea una camara en directo accesible para
cualquiera que probara la URL. Son imagenes de personas identificadas: en
cualquier regimen tipo RGPD eso es dato de categoria especial.

LA CORRECCION
-------------
Bucket privado (supabase/rls_edge.sql) y URLs FIRMADAS con caducidad. La
privacidad la da la politica del bucket, no lo dificil que sea adivinar el
nombre del fichero: el nombre no es un control de seguridad y aqui no se trata
como tal.

DOS PIEZAS CON ACOPLAMIENTOS DISTINTOS
--------------------------------------
  * Fotos de eventos: el edge guarda la URL en historial.foto_url, asi que
    pasar de publica a firmada NO requiere ningun cambio en el frontend —
    sigue siendo una URL. Caduca a la vez que expira la retencion.

  * Preview en vivo: hoy el frontend CONSTRUYE la URL el mismo a partir del
    nombre fijo del fichero. Con bucket privado eso deja de funcionar, asi que
    el edge publica la URL firmada en estado_sistema (dentro del JSON de
    camaras que el heartbeat ya escribe) y el frontend debe LEERLA de ahi.
    Ese es el unico cambio que hay que hacer fuera de este repositorio.

Por eso STORAGE_PRIVADO viene en false: activarlo sin haber aplicado el SQL y
sin haber tocado el frontend dejaria el preview roto. El arranque lo avisa.
"""

from config.settings import STORAGE_PRIVADO, DIAS_RETENCION

# Bucket unico de capturas
BUCKET = "capturas"

# Nombre del frame de preview en vivo. Se sobreescribe en cada subida.
# No es un secreto: con el bucket en privado no se puede leer sin firma.
PREVIEW = "live_preview.jpg"

# Validez de la URL firmada del preview. Solo tiene que aguantar mas que el
# intervalo del heartbeat, que la renueva cada 30s.
VALIDEZ_PREVIEW = 3600

# Margen sobre la retencion para que la URL de una foto no caduque ANTES de
# que la limpieza borre su registro (si no, quedan huecos en el historial).
_MARGEN_RETENCION_DIAS = 1


def modo_privado():
    """True si se usan URLs firmadas."""
    return STORAGE_PRIVADO


def validez_fotos_segundos():
    """Caducidad de las URLs de fotos de evento, alineada a la retencion."""
    return int((DIAS_RETENCION + _MARGEN_RETENCION_DIAS) * 24 * 3600)


def extraer_url_firmada(respuesta):
    """
    Saca la URL de la respuesta de create_signed_url.

    La clave cambia segun la version de storage3 ('signedURL', 'signedUrl',
    'signed_url'), asi que se aceptan las tres en vez de fiarse de una. No he
    podido probarlo contra la API real desde aqui, y equivocarse de clave
    dejaria las fotos sin URL en silencio.
    """
    if respuesta is None:
        return None
    if isinstance(respuesta, str):
        return respuesta or None
    if isinstance(respuesta, dict):
        for clave in ("signedURL", "signedUrl", "signed_url", "signedurl"):
            valor = respuesta.get(clave)
            if valor:
                return valor
    return None


def url_de(cliente, ruta, validez_segundos=None):
    """
    URL para un objeto del bucket.

    Privada -> URL firmada que caduca. Publica -> comportamiento heredado.
    Retorna None si no se pudo generar (el llamante decide que hacer).
    """
    almacen = cliente.storage.from_(BUCKET)

    if not STORAGE_PRIVADO:
        return almacen.get_public_url(ruta)

    if validez_segundos is None:
        validez_segundos = validez_fotos_segundos()

    try:
        return extraer_url_firmada(
            almacen.create_signed_url(ruta, validez_segundos)
        )
    except Exception as e:
        print(f"[Storage] No se pudo firmar la URL de {ruta}: {e}")
        return None


def url_preview(cliente):
    """URL del frame de preview en vivo, para publicarla en estado_sistema."""
    return url_de(cliente, PREVIEW, VALIDEZ_PREVIEW)


def texto_aviso():
    """
    Aviso de arranque si las capturas siguen siendo publicas.
    Retorna None si la configuracion es correcta.
    """
    if STORAGE_PRIVADO:
        return None
    return (
        "\n AVISO DE SEGURIDAD: el bucket de capturas es PUBLICO.\n"
        "    Las fotos faciales de cada acceso y el preview en vivo quedan\n"
        "    en URLs sin autenticacion ni caducidad, y el preview ademas en\n"
        "    una ruta fija y adivinable.\n"
        "    Aplica supabase/rls_edge.sql (seccion 4), haz que el frontend lea\n"
        "    la URL del preview de estado_sistema, y pon STORAGE_PRIVADO=true.\n"
    )
