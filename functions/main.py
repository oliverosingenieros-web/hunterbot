"""Cloud Functions for Firebase (Python 3.12).

Endpoints:
1. telegram_webhook: Recibe mensajes de Telegram en tiempo real vía Webhook.
2. scheduled_hunter: Tarea programada semanal/diaria para buscar chollos automáticamente.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from firebase_admin import initialize_app
from firebase_functions import https_fn, scheduler_fn
from firebase_functions.options import SupportedRegion

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.engine import HunterEngine
from hunterbot.models import ItemCategory, Operation, SearchCriteria
from hunterbot.telegram_bot import InteractiveTelegramBot

# Inicializar Firebase Admin
initialize_app()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@https_fn.on_request(region=SupportedRegion.US_CENTRAL1, memory=512, timeout_sec=120)
def telegram_webhook(req: https_fn.Request) -> https_fn.Response:
    """Webhook HTTPS que Telegram llama cada vez que envías un mensaje."""
    if req.method != "POST":
        return https_fn.Response("Only POST accepted", status=405)

    try:
        data = req.get_json(silent=True)
        if not data or "message" not in data:
            return https_fn.Response("OK", status=200)

        message = data["message"]

        async def _handle():
            bot = InteractiveTelegramBot("config.yaml")
            await bot.process_message(message)

        asyncio.run(_handle())
        return https_fn.Response("OK", status=200)
    except Exception as e:
        logger.error("Error en webhook de Telegram: %s", e)
        return https_fn.Response(f"Error: {e}", status=500)


@scheduler_fn.on_schedule(
    schedule="every monday 09:00",
    timezone="Europe/Madrid",
    region=SupportedRegion.US_CENTRAL1,
    memory=512,
    timeout_sec=300,
)
def scheduled_hunter(event: scheduler_fn.ScheduledEvent) -> None:
    """Ejecución automática semanal de rastreo y resumen de chollos."""
    logger.info("⏰ Ejecutando rastreo programado en Firebase Cloud...")
    cfg = load_config("config.yaml")

    async def _run_search():
        engine = HunterEngine(cfg)
        ai = HunterAIAdvisor()
        try:
            # 1. Buscar casas
            criteria_casa = SearchCriteria(
                category=ItemCategory.REAL_ESTATE,
                location="Malaga",
                price_max=300000,
                operation=Operation.SALE,
            )
            res_casa = await engine.search_all(criteria_casa, project_name="Casa")

            # 2. Buscar barcos
            criteria_barco = SearchCriteria(
                category=ItemCategory.BOAT,
                query="velero",
            )
            res_barco = await engine.search_all(criteria_barco, project_name="Barco")

            # 3. Reporte semanal con IA
            top_items = engine.db.get_items(limit=10)
            items_data = [i.__dict__ for i in top_items]
            report = await ai.generate_weekly_report(items_data)

            # Notificar resumen general
            bot = InteractiveTelegramBot("config.yaml")
            await bot.send_message(
                chat_id=cfg.telegram.group_chat_id,
                text=f"📅 *REPORTE AUTOMÁTICO SEMANAL CON IA*\n\n{report}",
            )
        finally:
            await engine.close()

    asyncio.run(_run_search())
