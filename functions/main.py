"""Cloud Functions for Firebase (Python 3.12).

Endpoints:
1. telegram_webhook: Recibe mensajes de Telegram en tiempo real vía Webhook.
2. scheduled_hunter: Tarea programada que ejecuta las alertas recurrentes activadas por el usuario por hilo.
3. api_search: API REST para invocar búsquedas estructuradas desde cuadernos Jupyter / Gemini Function Calling.
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
        update_id = data.get("update_id")

        async def _handle():
            bot = InteractiveTelegramBot("config.yaml")
            await bot.process_message(message, update_id)

        asyncio.run(_handle())
        return https_fn.Response("OK", status=200)
    except Exception as e:
        logger.error("Error en webhook de Telegram: %s", e, exc_info=True)
        return https_fn.Response("OK", status=200)


@https_fn.on_request(region=SupportedRegion.US_CENTRAL1, memory=512, timeout_sec=120)
def api_search(req: https_fn.Request) -> https_fn.Response:
    """Endpoint REST JSON para invocar el motor de búsqueda desde Gemini o cuadernos externos.
    
    Acepta GET y POST:
    - GET /api_search?q=zar+formenti&category=boat&location=malaga
    - POST /api_search con body JSON: { "query": "...", "category": "boat", "location": "..." }
    """
    # Manejar CORS para invocaciones desde navegador o Colab
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Content-Type": "application/json; charset=utf-8",
    }

    if req.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=cors_headers)

    query = ""
    category_str = "other"
    location = None
    price_max = None
    price_min = None

    if req.method == "POST":
        data = req.get_json(silent=True) or {}
        query = data.get("query") or data.get("q") or ""
        category_str = data.get("category") or "other"
        location = data.get("location")
        price_max = data.get("price_max")
        price_min = data.get("price_min")
    elif req.method == "GET":
        query = req.args.get("q") or req.args.get("query") or ""
        category_str = req.args.get("category") or "other"
        location = req.args.get("location")
        if req.args.get("price_max"):
            try:
                price_max = float(req.args.get("price_max"))
            except ValueError:
                pass

    if not query and not location:
        return https_fn.Response(
            json.dumps({"error": "Parámetro 'query' o 'location' requerido", "items": []}),
            status=400,
            headers=cors_headers,
        )

    # Mapear categoría
    cat = ItemCategory.OTHER
    cat_lower = category_str.lower()
    if "boat" in cat_lower or "barco" in cat_lower:
        cat = ItemCategory.BOAT
    elif "estate" in cat_lower or "inmob" in cat_lower or "casa" in cat_lower or "terreno" in cat_lower:
        cat = ItemCategory.REAL_ESTATE
    elif "product" in cat_lower or "zapat" in cat_lower or "ordenad" in cat_lower:
        cat = ItemCategory.PRODUCT

    criteria = SearchCriteria(
        category=cat,
        query=query,
        location=location,
        price_max=price_max,
        price_min=price_min,
        operation=Operation.SALE,
    )

    cfg = load_config("config.yaml")

    async def _do_search():
        engine = HunterEngine(cfg)
        try:
            results = await engine.search_all(criteria)
            items_list = []
            for opp in results:
                it = opp.item
                items_list.append({
                    "id": it.id,
                    "title": it.title,
                    "price": it.price,
                    "provider": it.provider,
                    "url": it.url,
                    "location": it.location,
                    "length_m": it.length_m,
                    "size_m2": it.size_m2,
                    "rooms": it.rooms,
                    "year_built": it.year_built,
                    "score": round(opp.score, 2),
                    "reasons": opp.reasons,
                    "description": it.description,
                })
            return items_list
        finally:
            await engine.close()

    try:
        items = asyncio.run(_do_search())
        payload = {
            "success": True,
            "query": query,
            "category": cat.value,
            "total": len(items),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": items,
        }
        return https_fn.Response(json.dumps(payload, ensure_ascii=False), status=200, headers=cors_headers)
    except Exception as e:
        logger.error("Error en api_search: %s", e, exc_info=True)
        return https_fn.Response(
            json.dumps({"success": False, "error": str(e), "results": []}),
            status=500,
            headers=cors_headers,
        )


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

                    doc.reference.update({"last_executed": now.isoformat()})

            await engine.close()
        except Exception as e:
            logger.error("Error en scheduled_hunter: %s", e)

    asyncio.run(_run_custom_alerts())
