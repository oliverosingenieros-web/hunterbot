"""Bot interactivo de Telegram con IA y búsqueda en tiempo real."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.engine import HunterEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    """Escapa caracteres especiales de Markdown v1 de Telegram en texto plano.
    
    Solo escapa dentro de texto que NO sea ya un enlace o formato intencional.
    Para uso en títulos scrapeados, ubicaciones, etc.
    """
    # Escapar caracteres que rompen Markdown v1: _ * [ ] ( ) ~
    return re.sub(r'([_*\[\]()~`>#+=|{}.!-])', r'\\\1', text)


class InteractiveTelegramBot:
    """Escucha mensajes en Telegram, los interpreta con IA y ejecuta búsquedas."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.cfg = load_config(config_path)
        self.bot_token = self.cfg.telegram.bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.ai = HunterAIAdvisor()

    async def send_message(self, chat_id: str | int, text: str, thread_id: int | None = None) -> None:
        """Envía un mensaje a Telegram con fallback si Markdown falla."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload: dict = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            if thread_id:
                payload["message_thread_id"] = thread_id

            resp = await client.post(f"{self.base_url}/sendMessage", json=payload)

            # Si falla por Markdown mal formado, reintentar sin parse_mode
            if resp.status_code != 200:
                logger.warning(
                    "Markdown falló (status=%d). Reintentando sin parse_mode. Error: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                payload.pop("parse_mode", None)
                # Limpiar markdown residual del texto
                clean_text = text.replace("*", "").replace("_", "").replace("`", "")
                payload["text"] = clean_text
                resp2 = await client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp2.status_code != 200:
                    logger.error("Envío sin Markdown también falló: %s", resp2.text[:200])

    async def create_forum_topic(self, chat_id: str | int, name: str, icon_color: int | None = None) -> int | None:
        """Crea dinámicamente un nuevo tema/hilo en un supergrupo de Telegram."""
        # Limpiar el nombre: sin caracteres que rompan la API
        clean_name = name[:120].strip()
        if not clean_name:
            clean_name = "🎯 Nueva búsqueda"

        async with httpx.AsyncClient(timeout=15.0) as client:
            payload: dict = {
                "chat_id": chat_id,
                "name": clean_name,
            }
            if icon_color:
                payload["icon_color"] = icon_color
            try:
                resp = await client.post(f"{self.base_url}/createForumTopic", json=payload)
                if resp.status_code == 200 and resp.json().get("ok"):
                    topic_id = resp.json()["result"]["message_thread_id"]
                    logger.info("Tema creado: id=%s ('%s')", topic_id, clean_name)
                    return topic_id
                logger.warning("No se pudo crear topic: %s", resp.text[:200])
            except Exception as e:
                logger.error("Error creando topic: %s", e)
        return None

    async def process_message(self, message: dict) -> None:
        """Procesa un mensaje entrante de Telegram."""
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        thread_id = message.get("message_thread_id")

        if not text or not chat_id:
            return

        logger.info("📩 Mensaje (chat=%s, thread=%s): '%s'", chat_id, thread_id, text[:80])

        # Ignorar mensajes del propio bot
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            return

        # Comandos básicos
        if text.startswith("/start") or text.startswith("/help"):
            help_msg = (
                "🎯 *¡Hola! Soy HunterBot con Asesor IA y Búsqueda Automática.*\n\n"
                "💡 *¿Cómo funciona?*\n"
                "Escríbeme cualquier petición en lenguaje natural:\n"
                '  "Quiero comprar una parcela en la sierra de Madrid por 70.000€"\n'
                '  "Busca veleros oceánicos de 12 metros por menos de 60.000€"\n\n'
                "🚀 *¿Qué haré?*\n"
                "1. Abriré un Tema dedicado para tu consulta.\n"
                "2. Te daré un diagnóstico y consejos de experto.\n"
                "3. Rastrearé portales y te publicaré los mejores chollos.\n"
                "4. Podrás seguir afinando dentro de ese mismo tema.\n\n"
                "📊 Pide /semanal para un reporte ejecutivo."
            )
            await self.send_message(chat_id, help_msg, thread_id)
            return

        if text.startswith("/semanal") or "resumen semanal" in text.lower():
            await self.send_message(chat_id, "🧠 Generando análisis y reporte semanal con IA...", thread_id)
            engine = HunterEngine(self.cfg)
            try:
                top_items = engine.db.get_items(limit=10)
                items_data = [{"title": i.title, "price": i.price, "location": i.location, "provider": i.provider} for i in top_items]
                report = await self.ai.generate_weekly_report(items_data)
                await self.send_message(chat_id, f"📊 REPORTE EJECUTIVO SEMANAL\n\n{report}", thread_id)
            finally:
                await engine.close()
            return

        # Consultar al Asesor de IA
        try:
            consult = await self.ai.consult_and_parse(text)
        except Exception as e:
            logger.error("Error en IA: %s", e)
            await self.send_message(chat_id, "⚠️ Error analizando tu petición. Inténtalo de nuevo.", thread_id)
            return

        criteria = consult["criteria"]
        topic_title = consult["topic_title"]
        tags = consult["tags"]
        advice = consult["advice"]
        project_name = consult["project_name"]

        # Determinar el hilo de destino
        target_thread = thread_id
        is_general = not thread_id or thread_id == 1

        if is_general:
            # Crear tema dedicado automáticamente
            new_thread = await self.create_forum_topic(chat_id, topic_title)
            if new_thread:
                target_thread = new_thread
                # Referencia al nuevo tema desde General
                chat_id_clean = str(chat_id).replace("-100", "")
                await self.send_message(
                    chat_id,
                    f"🎯 He abierto el tema '{topic_title}' para tu búsqueda.\n"
                    f"👉 Entra al tema para ver los resultados.",
                    thread_id,
                )

        # Publicar tarjeta de asesoramiento en el hilo correspondiente
        tags_str = " ".join(tags)
        consultation_msg = (
            f"🧠 ASESORAMIENTO HUNTERBOT\n"
            f"🏷️ {tags_str}\n\n"
            f"💡 Análisis de Mercado:\n{advice}\n\n"
            f"🔎 Rastreando oportunidades en tiempo real..."
        )
        await self.send_message(chat_id, consultation_msg, target_thread)

        # Ejecutar rastreo
        engine = HunterEngine(self.cfg)
        try:
            results = await engine.search_all(criteria, project_name=project_name)

            # Filtrar por threshold, pero si no hay suficientes, mostrar los mejores
            filtered = [r for r in results if r.score >= self.cfg.opportunity_threshold]
            if not filtered and results:
                # Mostrar los mejores 5 aunque no superen el threshold
                filtered = results[:5]

            if not filtered:
                query_desc = criteria.query or criteria.location or "tu búsqueda"
                await self.send_message(
                    chat_id,
                    f"🔍 He rastreado los portales para '{query_desc}' pero no he detectado anuncios activos en este momento.\n\n"
                    f"💬 Siguiente paso: Puedes pedirme ampliar el presupuesto, buscar en zonas cercanas, "
                    f"o cambiar los criterios respondiendo aquí mismo.",
                    target_thread,
                )
            else:
                summary = f"🎉 He encontrado {len(filtered)} opciones:\n\n"
                for opp in filtered[:7]:
                    item = opp.item
                    # Formatear precio
                    if item.price > 0:
                        price_fmt = f"{item.price:,.0f} €".replace(",", ".")
                    else:
                        price_fmt = "Consultar"

                    # Limpiar título para Markdown seguro
                    safe_title = item.title[:50].replace("[", "(").replace("]", ")").replace("*", "")

                    # Construir línea
                    summary += f"{opp.emoji} [{opp.score:.1f}/10] {safe_title} - {price_fmt}\n"
                    if item.url:
                        summary += f"   🔗 {item.url}\n"

                summary += "\n💬 Puedes pedirme más detalles de cualquiera o seguir afinando."
                await self.send_message(chat_id, summary, target_thread)
        except Exception as e:
            logger.error("Error en búsqueda: %s", e)
            await self.send_message(
                chat_id,
                "⚠️ Hubo un error al rastrear los portales. Inténtalo de nuevo en unos segundos.",
                target_thread,
            )
        finally:
            await engine.close()

    async def run(self) -> None:
        """Modo polling para ejecución local."""
        logger.info("🚀 Bot interactivo escuchando mensajes...")
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
