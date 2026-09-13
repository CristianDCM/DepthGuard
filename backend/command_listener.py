"""
Listener de comandos del frontend vía tabla `comandos_edge`.

Hilo que hace polling cada 2 segundos buscando comandos pendientes.
Cuando encuentra uno de tipo INICIAR_REGISTRO, activa el modo_registro
del pipeline IA y monitorea el progreso hasta completar o fallar.
"""

import time
import json
import threading

from backend.supabase_cliente import obtener_cliente
from backend.autorizacion_registro import validar_comando_registro
from config.settings import PERMITIR_REENROLAMIENTO, REGISTRO_HMAC_SECRET

# Intervalo de polling (segundos)
_POLL_INTERVAL = 2

# Total de ángulos requeridos para completar un registro
_ANGULOS_REQUERIDOS = 5


def iniciar_command_listener(modo_registro):
    """
    Hilo principal del listener. Corre en loop infinito.
    modo_registro: instancia compartida de EstadoRegistro (thread-safe).
    """
    supabase = obtener_cliente()
    print("[CommandListener] Activo — polling cada 2s")

    while True:
        try:
            _poll_comandos(supabase, modo_registro)
        except Exception as e:
            print(f"[CommandListener] Error en polling: {e}")

        time.sleep(_POLL_INTERVAL)


def _poll_comandos(supabase, modo_registro):
    """Busca comandos pendientes y los ejecuta."""
    resp = supabase.table("comandos_edge") \
        .select("*") \
        .eq("estado", "pendiente") \
        .order("created_at") \
        .limit(1) \
        .execute()

    if not resp.data:
        return

    comando = resp.data[0]
    tipo = comando["tipo"]
    cmd_id = comando["id"]

    if tipo == "INICIAR_REGISTRO":
        _ejecutar_registro(supabase, comando, modo_registro)
    elif tipo == "CANCELAR_REGISTRO":
        _ejecutar_cancelar(supabase, cmd_id, modo_registro)
    else:
        # Tipo desconocido — marcar como error
        _actualizar_comando(supabase, cmd_id, "error", resultado={
            "error": f"Tipo de comando desconocido: {tipo}"
        })


def _cargar_usuario_objetivo(supabase, usuario_id):
    """
    Lee de la BD el usuario al que apunta el comando.

    Es la fuente de verdad sobre a quien se va a enrolar: el comando NO es de
    confianza. Retorna None si no existe o esta inactivo (la RLS del edge solo
    deja ver usuarios activos).
    """
    if not usuario_id:
        return None
    try:
        resp = supabase.table("usuarios") \
            .select("id, nombre, num_angulos, embeddings_json, activo") \
            .eq("id", usuario_id) \
            .limit(1) \
            .execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        # Ante la duda, no autorizar: devolver None hace que el comando se
        # rechace en vez de ejecutarse a ciegas.
        print(f"[CommandListener] Error leyendo usuario objetivo: {e}")
        return None


def _ejecutar_registro(supabase, comando, modo_registro):
    """
    Autoriza el comando y, si procede, activa el modo registro en el pipeline.
    El pipeline (en su hilo) captura embeddings y los almacena en modo_registro.
    Este hilo actualiza el progreso en la tabla comandos_edge.
    """
    cmd_id = comando["id"]
    usuario_id = comando.get("usuario_id")

    # === AUTORIZACION (hallazgo C4) ===
    # Antes se enrolaba biometria en el usuario_id que viniera en el comando
    # sin comprobar nada, asi que quien pudiera escribir en `comandos_edge`
    # sobrescribia la cara de un administrador con la suya.
    usuario_db = _cargar_usuario_objetivo(supabase, usuario_id)
    autorizado, motivo, contexto = validar_comando_registro(
        comando, usuario_db,
        permitir_reenrolamiento_local=PERMITIR_REENROLAMIENTO,
        secreto_hmac=REGISTRO_HMAC_SECRET or None,
    )

    if not autorizado:
        print(f"[CommandListener]  REGISTRO RECHAZADO ({usuario_id}): {motivo}")
        _actualizar_comando(supabase, cmd_id, "error", resultado={
            "error": f"Registro no autorizado: {motivo}",
            "motivo_seguridad": motivo,
            "usuario_id": usuario_id,
            "nombre_comando": contexto.get("nombre_comando"),
            "nombre_db": contexto.get("nombre_db"),
            "es_reenrolamiento": contexto.get("es_reenrolamiento"),
        })
        return

    # Nombre AUTORITATIVO: el de la base de datos, nunca el del comando. Asi
    # el HUD y la auditoria muestran a quien se esta enrolando de verdad.
    nombre = contexto.get("nombre_db") or "Sin nombre"

    if contexto.get("es_reenrolamiento"):
        print(f"[CommandListener]  RE-ENROLAMIENTO autorizado de '{nombre}': "
              f"se sobrescribe su biometria existente")

    print(f"[CommandListener]  Registro iniciado: {nombre} (usuario: {usuario_id})")

    # Marcar como en progreso
    _actualizar_comando(supabase, cmd_id, "en_progreso", progreso=0)

    # Activar modo registro en el pipeline
    modo_registro.iniciar(nombre)

    # Monitorear progreso hasta completar o timeout
    timeout = 120  # 2 minutos máximo
    t_inicio = time.time()
    ultimo_paso_reportado = -1

    while time.time() - t_inicio < timeout:
        # Verificar si se canceló internamente (flag directo)
        if not modo_registro.activo and not modo_registro.completado:
            _actualizar_comando(supabase, cmd_id, "cancelado", resultado={
                "motivo": "Registro cancelado"
            })
            print(f"[CommandListener]  Registro cancelado: {nombre}")
            return

        # Verificar si la web envió un comando CANCELAR_REGISTRO
        try:
            cancel_resp = supabase.table("comandos_edge") \
                .select("id") \
                .eq("tipo", "CANCELAR_REGISTRO") \
                .eq("usuario_id", usuario_id) \
                .eq("estado", "pendiente") \
                .limit(1) \
                .execute()
            if cancel_resp.data:
                cancel_cmd_id = cancel_resp.data[0]["id"]
                modo_registro.activo = False
                _actualizar_comando(supabase, cancel_cmd_id, "completado", resultado={
                    "motivo": "Cancelación ejecutada"
                })
                _actualizar_comando(supabase, cmd_id, "cancelado", resultado={
                    "motivo": "Cancelado desde la web"
                })
                print(f"[CommandListener]  Registro cancelado desde la web: {nombre}")
                return
        except Exception:
            pass  # No romper el registro si falla la verificación

        # Actualizar progreso si cambió
        paso_actual = modo_registro.paso
        if paso_actual != ultimo_paso_reportado:
            ultimo_paso_reportado = paso_actual
            _actualizar_comando(supabase, cmd_id, "en_progreso",
                                progreso=paso_actual,
                                resultado={
                                    "angulo_solicitado": modo_registro.angulo_solicitado,
                                    "angulos_capturados": modo_registro.angulos_capturados,
                                })

        # Verificar si hay suficientes embeddings
        embeddings = modo_registro.embeddings
        if len(embeddings) >= _ANGULOS_REQUERIDOS:
            # Guardar embeddings en la tabla usuarios
            try:
                embeddings_json = [emb.tolist() if hasattr(emb, 'tolist') else emb
                                   for emb in embeddings[:_ANGULOS_REQUERIDOS]]

                supabase.table("usuarios").update({
                    "embeddings_json": embeddings_json,
                    "num_angulos": _ANGULOS_REQUERIDOS,
                }).eq("id", usuario_id).execute()

                # Marcar registro como completado
                modo_registro.completar({"usuario_id": usuario_id, "angulos": _ANGULOS_REQUERIDOS})
                modo_registro.recargar_cache = True

                _actualizar_comando(supabase, cmd_id, "completado",
                                    progreso=_ANGULOS_REQUERIDOS,
                                    resultado={"angulos": _ANGULOS_REQUERIDOS})

                print(f"[CommandListener]  Registro completo: {nombre} ({_ANGULOS_REQUERIDOS} embeddings)")
                return

            except Exception as e:
                modo_registro.completar({"error": str(e)})
                _actualizar_comando(supabase, cmd_id, "error", resultado={
                    "error": f"Error guardando embeddings: {e}"
                })
                print(f"[CommandListener]  Error guardando embeddings: {e}")
                return

        time.sleep(1)  # Revisar cada segundo

    # Timeout
    embeds_capturados = len(modo_registro.embeddings)
    modo_registro.completar({"error": "Timeout"})
    _actualizar_comando(supabase, cmd_id, "error", resultado={
        "error": f"Timeout: solo se capturaron {embeds_capturados}/{_ANGULOS_REQUERIDOS} embeddings"
    })
    print(f"[CommandListener]  Timeout registro: {nombre} ({embeds_capturados} embeddings)")


def _ejecutar_cancelar(supabase, cmd_id, modo_registro):
    """Cancela un registro en progreso."""
    if modo_registro.activo:
        modo_registro.activo = False
        print("[CommandListener]  Registro cancelado por comando")

    _actualizar_comando(supabase, cmd_id, "completado", resultado={
        "motivo": "Cancelación ejecutada"
    })


def _actualizar_comando(supabase, cmd_id, estado, progreso=None, resultado=None):
    """Actualiza el estado de un comando en Supabase."""
    update = {"estado": estado, "updated_at": "now()"}
    if progreso is not None:
        update["progreso"] = progreso
    if resultado is not None:
        update["resultado"] = resultado

    try:
        supabase.table("comandos_edge").update(update).eq("id", cmd_id).execute()
    except Exception as e:
        print(f"[CommandListener] Error actualizando comando: {e}")
