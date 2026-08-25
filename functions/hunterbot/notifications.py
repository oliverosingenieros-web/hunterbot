"""Sistema de notificaciones por Telegram con soporte para Topics/Hilos por proyecto."""

from __future__ import annotations

import logging
from typing import Any

from hunterbot.config import HunterConfig
from hunterbot.http_client import HunterHTTPClient
from hunterbot.models import OpportunityScore

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Envía notificaciones enriquecidas a Telegram."""

    def __init__(self, config: HunterConfig, http_client: HunterHTTPClient) -> None:
        self.config = config
        self.http = http_client
        self.tg_cfg = config.telegram

    @property
    def is_enabled(self) -> bool:
        return bool(
            self.tg_cfg.enabled and self.tg_cfg.bot_token and self.tg_cfg.group_chat_id
        )

    async def notify_opportunity(
        self,
        opp: OpportunityScore,
        project_name: str | None = None,
    ) -> bool:
        """Envía una alerta de oportunidad a Telegram en el Topic correspondiente."""
        if not self.is_enabled:
            return False

        if opp.score < self.tg_cfg.min_score:
            return False

        item = opp.item
        thread_id = None
        if project_name and self.tg_cfg.topics:
            thread_id = self.tg_cfg.topics.get(project_name)

        # Formato del mensaje
        reasons_text = (
            "\n".join([f"• {r}" for r in opp.reasons])
            if opp.reasons
            else "• Buena relación calidad/precio"
        )
        price_fmt = f"{item.price:,.0f} {item.currency}".replace(",", ".")
        m2_info = f" ({item.price_per_m2:.0f} €/m²)" if item.price_per_m2 else ""

        tag_project = f"📁 #{project_name.replace(' ', '_')}\n" if project_name else ""

        message = (
            f"{opp.emoji} *OPORTUNIDAD ({opp.score}/10)*\n"
            f"{tag_project}"
            f"*{item.title}*\n\n"
            f"💰 *Precio:* {price_fmt}{m2_info}\n"
            f"📍 *Ubicación:* {item.location or 'No especificada'}\n"
            f"🔌 *Fuente:* {item.provider}\n\n"
            f"*Razones:*\n{reasons_text}\n\n"
            f"🔗 [Ver en {item.provider.capitalize()}]({item.url})"
        )

        url = f"https://api.telegram.org/bot{self.tg_cfg.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.tg_cfg.group_chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        if thread_id:
            payload["message_thread_id"] = thread_id

        try:
            resp = await self.http.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(
                    "Notificación Telegram enviada: %s (%s)", item.title, opp.score
                )
                return True
            else:
                logger.error("Error enviando a Telegram: %s", resp.text)
                return False
        except Exception as e:
            logger.error("Fallo al contactar API de Telegram: %s", e)
            return False

    async def notify_health_alert(self, provider_name: str, issue: str) -> bool:
        """Envía una alerta de salud del sistema al administrador."""
        if not self.tg_cfg.enabled or not self.tg_cfg.bot_token or not self.tg_cfg.admin_chat_id:
            return False

        message = (
            f"⚠️ *ALERTA DE SALUD: HUNTERBOT*\n\n"
            f"El proveedor `{provider_name}` está reportando problemas continuos.\n"
            f"Detalles: {issue}\n\n"
            f"Revisa si ha cambiado el CSS de la página web o si el bot ha sido bloqueado por IP."
        )

        url = f"https://api.telegram.org/bot{self.tg_cfg.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.tg_cfg.admin_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }

        try:
            resp = await self.http.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Alerta de salud enviada a admin para %s", provider_name)
                return True
            logger.error("Error enviando alerta de salud: %s", resp.text)
        except Exception as e:
            logger.error("Fallo enviando alerta de salud: %s", e)
        return False
