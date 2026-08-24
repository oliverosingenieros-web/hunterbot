"""Cloud Functions for Firebase (Python 3.12).

Endpoints:
1. telegram_webhook: Recibe mensajes de Telegram en tiempo real vía Webhook.
2. scheduled_hunter: Tarea programada que ejecuta las alertas recurrentes activadas por el usuario por hilo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from firebase_admin import initialize_app
from firebase_functions import https_fn, scheduler_fn
from firebase_functions.options import SupportedRegion

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.database_firebase import FirestoreDatabase
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
        logger.error("Error en webhook de Telegram: %s", e, exc_info=True)
        return https_fn.Response("OK", status=200)


@scheduler_fn.on_schedule(
    schedule="every day 09:00",
    timezone="Europe/Madrid",
    region=SupportedRegion.US_CENTRAL1,
    memory=512,
    timeout_sec=300,
)
def scheduled_hunter(event: scheduler_fn.ScheduledEvent) -> None:
    """Ejecuta únicamente las búsquedas recurrentes que el usuario haya solicitado explícitamente en sus hilos."""
    logger.info("⏰ Comprobando alertas recurrentes solicitadas por el usuario...")
    cfg = load_config("config.yaml")
    db = FirestoreDatabase()

    if not db.enabled:
        logger.info("Firestore no habilitado. Omitiendo reporte automático.")
        return

    async def _run_custom_alerts():
        try:
            alerts_ref = db.db.collection("active_alerts").where("active", "==", True).stream()
            now = datetime.now(timezone.utc)
            bot = InteractiveTelegramBot("config.yaml")
            engine = HunterEngine(cfg)

            for doc in alerts_ref:
                alert = doc.to_dict()
                chat_id = alert.get("chat_id")
                thread_id = alert.get("thread_id")
                interval_days = alert.get("interval_days", 7)
                last_exec_str = alert.get("last_executed")

                # Comprobar si ha cumplido el plazo configurado por el usuario
                should_run = True
                if last_exec_str:
                    try:
                        last_dt = datetime.fromisoformat(last_exec_str)
                        if now - last_dt < timedelta(days=interval_days):
                            should_run = False
                    except Exception:
                        pass

                if should_run and chat_id and thread_id:
                    query = alert.get("query", "")
                    category_str = alert.get("category", "boat")
                    logger.info("Ejecutando alerta periódica para hilo %s (%s)", thread_id, query)

                    criteria = SearchCriteria(
                        category=ItemCategory(category_str),
                        query=query,
                        location=alert.get("location"),
                        price_max=alert.get("price_max"),
                    )

                    results = await engine.search_all(criteria)
                    filtered = [r for r in results if r.score >= cfg.opportunity_threshold]
                    if not filtered and results:
                        filtered = results[:6]

                    if filtered:
                        results_text, items_for_ai = bot._format_results(filtered)
                        analysis = await bot.ai.analyze_results(query, items_for_ai)

                        report_msg = (
                            f"🔔 ACTUALIZACIÓN PERIÓDICA PROGRAMADA (cada {interval_days} días):\n\n"
                            f"{results_text}\n\n"
                            f"🧠 ANÁLISIS DEL ASESOR:\n{analysis}\n\n"
                            f"💬 Para detener estas actualizaciones, responde 'detener búsqueda recurrente'."
                        )
                        await bot.send_message(chat_id, report_msg, thread_id)

                    # Actualizar fecha de última ejecución
                    doc.reference.update({"last_executed": now.isoformat()})

            await engine.close()
        except Exception as e:
            logger.error("Error en scheduled_hunter: %s", e)

    asyncio.run(_run_custom_alerts())
