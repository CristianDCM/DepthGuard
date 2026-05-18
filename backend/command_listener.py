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


def _ejecutar_registro(supabase, comando, modo_registro):
    """
    Activa el modo registro en el pipeline y monitorea el progreso.
    El pipeline (en su hilo) captura embeddings y los almacena en modo_registro.
    Este hilo actualiza el progreso en la tabla comandos_edge.
    """
    cmd_id = comando["id"]
    usuario_id = comando.get("usuario_id")
    nombre = comando.get("nombre", "Sin nombre")

    print(f"[CommandListener] 🎯 Registro iniciado: {nombre} (usuario: {usuario_id})")

    # Marcar como en progreso
    _actualizar_comando(supabase, cmd_id, "en_progreso", progreso=0)

    # Activar modo registro en el pipeline
    modo_registro.iniciar(nombre)

    # Monitorear progreso hasta completar o timeout
    timeout = 120  # 2 minutos máximo
    t_inicio = time.time()
    ultimo_paso_reportado = -1

    while time.time() - t_inicio < timeout:
        # Verificar si se canceló externamente
        if not modo_registro.activo and not modo_registro.completado:
            _actualizar_comando(supabase, cmd_id, "cancelado", resultado={
                "motivo": "Registro cancelado"
            })
            print(f"[CommandListener] ❌ Registro cancelado: {nombre}")
            return

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

                print(f"[CommandListener] ✅ Registro completo: {nombre} ({_ANGULOS_REQUERIDOS} embeddings)")
                return

            except Exception as e:
                modo_registro.completar({"error": str(e)})
                _actualizar_comando(supabase, cmd_id, "error", resultado={
                    "error": f"Error guardando embeddings: {e}"
                })
                print(f"[CommandListener] ❌ Error guardando embeddings: {e}")
                return

        time.sleep(1)  # Revisar cada segundo

    # Timeout
    embeds_capturados = len(modo_registro.embeddings)
    modo_registro.completar({"error": "Timeout"})
    _actualizar_comando(supabase, cmd_id, "error", resultado={
        "error": f"Timeout: solo se capturaron {embeds_capturados}/{_ANGULOS_REQUERIDOS} embeddings"
    })
    print(f"[CommandListener] ⏰ Timeout registro: {nombre} ({embeds_capturados} embeddings)")


def _ejecutar_cancelar(supabase, cmd_id, modo_registro):
    """Cancela un registro en progreso."""
    if modo_registro.activo:
        modo_registro.activo = False
        print("[CommandListener] ❌ Registro cancelado por comando")

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
