"""Script para registrar el Webhook de Telegram contra Firebase."""

import sys
import httpx
from hunterbot.config import load_config


def set_webhook(function_url: str):
    cfg = load_config("config.yaml")
    token = cfg.telegram.bot_token
    if not token:
        print("❌ Error: bot_token no encontrado en config.yaml")
        return

    url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = {"url": function_url}

    resp = httpx.post(url, json=payload)
    if resp.status_code == 200 and resp.json().get("ok"):
        print(f"✅ ¡Webhook de Telegram configurado con éxito a: {function_url}")
    else:
        print(f"❌ Error configurando webhook: {resp.text}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python registrar_webhook.py <URL_DE_TU_FUNCION_FIREBASE>")
        print("Ejemplo: python registrar_webhook.py https://us-central1-mi-proyecto.cloudfunctions.net/telegram_webhook")
    else:
        set_webhook(sys.argv[1])
