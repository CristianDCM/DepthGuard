"""
Autorizacion de los comandos de registro biometrico (hallazgo C4).

EL PROBLEMA
-----------
El command listener leia una fila de `comandos_edge` y enrolaba biometria en
el `usuario_id` que viniera en ella, sin validar nada. Quien pudiera insertar
una fila con tipo=INICIAR_REGISTRO y el usuario_id de un administrador hacia
que el edge SOBRESCRIBIERA las plantillas de ese administrador con la cara del
atacante. Eso no es escalada de privilegios: es suplantacion directa, y despues
el atacante entra por la puerta como si fuera esa persona.

EL MODELO DE AMENAZA QUE SE CIERRA AQUI
---------------------------------------
Atacante que consigue ESCRIBIR en `comandos_edge` (RLS mal configurada, una
credencial de frontend filtrada) pero NO puede insertar en `usuarios`.

  - No puede crear una identidad nueva: el comando se rechaza si el
    usuario_id no existe o esta inactivo.
  - No puede apropiarse de una existente: re-enrolar a alguien que YA tiene
    plantillas exige autorizacion explicita, que el atacante no controla
    (config local del dispositivo, o una firma que no puede falsificar).

Queda fuera: un atacante que ademas pueda insertar en `usuarios` puede crear
una identidad y enrolarse en ella. Eso se corta con la RLS de `usuarios`
(supabase/rls_edge.sql), no desde aqui.

SOBRE LA FIRMA HMAC
-------------------
Es la defensa correcta, pero solo sirve si la firma se genera EN SERVIDOR (una
Edge Function de Supabase, o el backend de administracion). Nunca en el
navegador: un secreto en una SPA no es un secreto.

Y con honestidad sobre su alcance: el edge necesita el secreto para verificar,
asi que un edge comprometido puede falsificar comandos. Protege contra una base
de datos comprometida, que es de lo que va C4, no contra el dispositivo.
"""

import hmac
import hashlib


# Motivos de rechazo (estables, para poder auditarlos)
FALTA_USUARIO_ID = "comando sin usuario_id"
FIRMA_INVALIDA = "firma HMAC invalida o ausente"
USUARIO_NO_EXISTE = "el usuario_id no existe o esta inactivo"
NOMBRE_INCONSISTENTE = "el nombre del comando no coincide con el de la base de datos"
REENROLAMIENTO_NO_AUTORIZADO = "re-enrolamiento no autorizado: el usuario ya tiene biometria"


def firma_esperada(secreto, tipo, cmd_id, usuario_id, nombre, reenrolar):
    """
    HMAC-SHA256 del comando, en hexadecimal.

    Se firma tambien el id del propio comando, de modo que una firma valida no
    se puede reutilizar en una fila distinta, y el flag de re-enrolamiento, que
    si no iria fuera de la parte protegida y el atacante podria activarlo.
    """
    mensaje = "|".join([
        str(tipo or ""),
        str(cmd_id or ""),
        str(usuario_id or ""),
        str(nombre or ""),
        "1" if reenrolar else "0",
    ])
    return hmac.new(
        secreto.encode("utf-8"), mensaje.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def tiene_biometria(usuario_db):
    """True si el usuario ya tiene plantillas guardadas."""
    if not usuario_db:
        return False
    if usuario_db.get("num_angulos"):
        return True
    embeddings = usuario_db.get("embeddings_json")
    return bool(embeddings)


def validar_comando_registro(comando, usuario_db,
                             permitir_reenrolamiento_local=False,
                             secreto_hmac=None):
    """
    Decide si un comando INICIAR_REGISTRO puede ejecutarse.

    Args:
        comando: fila de `comandos_edge` (NO es de confianza).
        usuario_db: fila de `usuarios` para ese usuario_id, tal y como esta en
            la base de datos, o None si no existe o esta inactivo. Es la unica
            fuente de verdad sobre a quien se va a enrolar.
        permitir_reenrolamiento_local: config del DISPOSITIVO. Sin firma, es lo
            unico que el atacante no controla.
        secreto_hmac: si esta configurado, el comando debe venir firmado.

    Returns:
        (autorizado, motivo, contexto)
        contexto trae el nombre AUTORITATIVO (el de la base de datos, no el del
        comando) y si se trata de un re-enrolamiento, para el HUD y la
        auditoria.
    """
    contexto = {
        "usuario_id": comando.get("usuario_id"),
        "nombre_comando": comando.get("nombre"),
        "nombre_db": (usuario_db or {}).get("nombre"),
        "es_reenrolamiento": tiene_biometria(usuario_db),
        "firmado": bool(secreto_hmac),
    }

    usuario_id = comando.get("usuario_id")
    if not usuario_id:
        return False, FALTA_USUARIO_ID, contexto

    reenrolar_pedido = bool(comando.get("permitir_reenrolamiento"))

    # --- Firma, si el despliegue la usa ---
    if secreto_hmac:
        esperada = firma_esperada(
            secreto_hmac,
            comando.get("tipo"),
            comando.get("id"),
            usuario_id,
            comando.get("nombre"),
            reenrolar_pedido,
        )
        recibida = comando.get("firma") or ""
        # compare_digest: comparacion en tiempo constante
        if not hmac.compare_digest(esperada, str(recibida)):
            return False, FIRMA_INVALIDA, contexto

    # --- El objetivo tiene que existir y estar activo ---
    if not usuario_db:
        return False, USUARIO_NO_EXISTE, contexto

    # --- Consistencia de identidad ---
    # Si el comando dice un nombre, tiene que ser el de la base de datos. Asi
    # un atacante no puede disfrazar "sobrescribir al admin" de "dar de alta a
    # un empleado nuevo": o pone el nombre real del admin —y queda a la vista
    # en el HUD y en la auditoria— o el comando se rechaza.
    nombre_comando = (comando.get("nombre") or "").strip()
    nombre_db = (usuario_db.get("nombre") or "").strip()
    if nombre_comando and nombre_comando != nombre_db:
        return False, NOMBRE_INCONSISTENTE, contexto

    # --- Re-enrolamiento: el vector de suplantacion ---
    # Sobrescribir la biometria de alguien que ya la tiene es exactamente el
    # ataque. Exige autorizacion que el atacante no pueda darse a si mismo:
    # con firma, el flag va dentro de lo firmado; sin firma, solo vale la
    # config local del dispositivo.
    if contexto["es_reenrolamiento"]:
        autorizado = (reenrolar_pedido and bool(secreto_hmac)) or \
                     permitir_reenrolamiento_local
        if not autorizado:
            return False, REENROLAMIENTO_NO_AUTORIZADO, contexto

    return True, "", contexto
