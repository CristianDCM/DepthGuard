"""Notificaciones Web Push."""

import json
from pywebpush import webpush, WebPushException
from config.settings import VAPID_PRIVATE_KEY, VAPID_EMAIL


def enviar_push(suscripcion, mensaje):
    """Envía una notificación push a un suscriptor."""
    if not VAPID_PRIVATE_KEY:
        print("⚠️ VAPID no configurado. Push deshabilitado.")
        return False

    try:
        payload = json.dumps({
            "titulo": "🛡️ DepthGuard",
            "mensaje": mensaje,
            "tipo": "alerta"
        })

        webpush(
            subscription_info=suscripcion,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        return True

    except WebPushException as e:
        print(f"❌ Error push: {e}")
        return False
