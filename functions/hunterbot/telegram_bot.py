"""Bot interactivo de Telegram con IA y búsqueda en tiempo real."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.engine import HunterEngine
from hunterbot.models import ItemCategory, Operation, SearchCriteria

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class InteractiveTelegramBot:
    """Escucha mensajes en Telegram, los interpreta con IA y ejecuta búsquedas."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.cfg = load_config(config_path)
        self.bot_token = self.cfg.telegram.bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.ai = HunterAIAdvisor()

    async def send_message(self, chat_id: str | int, text: str, thread_id: int | None = None) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload: dict = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            if thread_id:
                payload["message_thread_id"] = thread_id
            
            resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
            # Si falla por caracteres especiales en Markdown, reintentar en texto plano
            if resp.status_code != 200:
                payload.pop("parse_mode", None)
                await client.post(f"{self.base_url}/sendMessage", json=payload)

    async def create_forum_topic(self, chat_id: str | int, name: str, icon_color: int | None = None) -> int | None:
        """Crea dinámicamente un nuevo tema/hilo en un supergrupo de Telegram."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload: dict = {
                "chat_id": chat_id,
                "name": name[:120],
            }
            if icon_color:
                payload["icon_color"] = icon_color
            try:
                resp = await client.post(f"{self.base_url}/createForumTopic", json=payload)
                if resp.status_code == 200 and resp.json().get("ok"):
                    topic_id = resp.json()["result"]["message_thread_id"]
                    logger.info("✨ Tema de foro creado en Telegram con éxito: id=%s ('%s')", topic_id, name)
                    return topic_id
                logger.warning("No se pudo crear topic en Telegram: %s", resp.text)
            except Exception as e:
                logger.error("Error creando topic en Telegram: %s", e)
        return None

    async def process_message(self, message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        thread_id = message.get("message_thread_id")

        if not text or not chat_id:
            return

        logger.info("📩 Mensaje recibido de Telegram (chat=%s, thread=%s): '%s'", chat_id, thread_id, text)

        # Comandos básicos
        if text == "/start" or text == "/help":
            help_msg = (
                "🎯 *¡Hola! Soy HunterBot con Asesor de Inversión y Búsqueda Automática.*\n\n"
                "💡 *¿Cómo funciona?*\n"
                "• Escríbeme cualquier petición en lenguaje natural en el canal **General**:\n"
                "  _\"Quiero comprar una parcela en la sierra de Madrid por 70.000€\"_\n"
                "  _\"Busca veleros oceánicos de 12 metros por menos de 60.000€\"_\n\n"
                "🚀 *¿Qué haré?*\n"
                "1. Abriré un **Tema dedicado** para tu consulta.\n"
                "2. Te daré un **diagnóstico y consejos de experto** (viabilidad, precios de zona, precauciones).\n"
                "3. Rastrearé portales y te publicaré los **mejores chollos** puntuados del 1 al 10.\n"
                "4. Podrás seguir conversando y afinando dentro de ese mismo tema.\n\n"
                "📊 O pide `/semanal` para un reporte ejecutivo de las mejores oportunidades."
            )
            await self.send_message(chat_id, help_msg, thread_id)
            return

        if text.startswith("/semanal") or "resumen semanal" in text.lower():
            await self.send_message(chat_id, "🧠 *Generando análisis y reporte semanal con IA...*", thread_id)
            engine = HunterEngine(self.cfg)
            try:
                top_items = engine.db.get_items(limit=10)
                items_data = [i.__dict__ for i in top_items]
                report = await self.ai.generate_weekly_report(items_data)
                await self.send_message(chat_id, f"📊 *REPORTE EJECUTIVO SEMANAL*\n\n{report}", thread_id)
            finally:
                await engine.close()
            return

        # Consultar al Asesor de IA
        consult = await self.ai.consult_and_parse(text)
        criteria = consult["criteria"]
        topic_title = consult["topic_title"]
        tags = consult["tags"]
        advice = consult["advice"]
        project_name = consult["project_name"]

        # Determinar el hilo de destino
        target_thread = thread_id
        is_general = (not thread_id or thread_id == 1)

        if is_general:
            # Crear tema dedicado automáticamente
            new_thread = await self.create_forum_topic(chat_id, topic_title)
            if new_thread:
                target_thread = new_thread
                await self.send_message(
                    chat_id,
                    f"🎯 *He abierto el tema dedicado [{topic_title}] para gestionar tu búsqueda.*\n"
                    f"👉 [Entrar al tema](https://t.me/c/{str(chat_id).replace('-100', '')}/{target_thread})",
                    thread_id,
                )

        # Publicar tarjeta de asesoramiento en el hilo correspondiente
        tags_str = " ".join(tags)
        consultation_msg = (
            f"🧠 *ASESORAMIENTO Y DIAGNÓSTICO HUNTERBOT*\n"
            f"🏷️ {tags_str}\n\n"
            f"💡 *Análisis de Mercado:*\n{advice}\n\n"
            f"🔎 *Rastreando oportunidades en tiempo real...*"
        )
        await self.send_message(chat_id, consultation_msg, target_thread)

        # Ejecutar rastreo
        engine = HunterEngine(self.cfg)
        try:
            results = await engine.search_all(criteria, project_name=project_name)
            filtered = [r for r in results if r.score >= self.cfg.opportunity_threshold]
            if not filtered and results:
                filtered = results[:4]

            if not filtered:
                await self.send_message(
                    chat_id,
                    f"🔍 He rastreado la red para '{criteria.query or criteria.location}'. No he detectado anuncios activos con precio en rango de forma inmediata.\n\n"
                    f"💬 *Siguiente paso:* Puedes pedirme ampliar el presupuesto o buscar en zonas cercanas respondiendo aquí mismo.",
                    target_thread,
                )
            else:
                summary = f"🎉 *He encontrado {len(filtered)} opciones y oportunidades:*\n\n"
                for opp in filtered[:5]:
                    item = opp.item
                    price_fmt = f"{item.price:,.0f} €".replace(",", ".") if item.price > 0 else "Consultar precio"
                    summary += f"{opp.emoji} *[{opp.score:.1f}/10]* [{item.title[:45]}]({item.url}) — *{price_fmt}*\n"

                summary += "\n💬 _Puedes pedirme más detalles de cualquiera de ellos o seguir afinando en este tema._"
                await self.send_message(chat_id, summary, target_thread)
        finally:
            await engine.close()



    async def run(self) -> None:
        logger.info("🚀 Bot interactivo de Telegram escuchando mensajes...")
        async with httpx.AsyncClient(timeout=40.0) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": self.last_update_id + 1, "timeout": 30},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        updates = data.get("result", [])
                        for u in updates:
                            self.last_update_id = u.get("update_id", self.last_update_id)
                            if "message" in u:
                                asyncio.create_task(self.process_message(u["message"]))
                except Exception as e:
                    logger.error("Error en loop de Telegram: %s", e)
                    await asyncio.sleep(5)


if __name__ == "__main__":
    bot = InteractiveTelegramBot()
    asyncio.run(bot.run())
