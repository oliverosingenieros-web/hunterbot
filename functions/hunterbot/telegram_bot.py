"""Bot interactivo de Telegram con IA conversacional y búsqueda en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.engine import HunterEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Memoria de contexto por hilo (topic) para conversación
# En Cloud Functions esto se resetea entre invocaciones, pero dentro de
# una misma invocación permite al bot recordar qué se buscó.
_topic_context: dict[str, str] = {}


class InteractiveTelegramBot:
    """Escucha mensajes en Telegram, los interpreta con IA y ejecuta búsquedas."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.cfg = load_config(config_path)
        self.bot_token = self.cfg.telegram.bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.ai = HunterAIAdvisor()

    async def send_message(self, chat_id: str | int, text: str, thread_id: int | None = None) -> None:
        """Envía un mensaje a Telegram. Sin Markdown para evitar errores de parseo."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Enviar siempre como texto plano — más fiable que Markdown
            payload: dict = {
                "chat_id": chat_id,
                "text": text[:4096],  # Límite de Telegram
                "disable_web_page_preview": True,
            }
            if thread_id:
                payload["message_thread_id"] = thread_id

            try:
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp.status_code != 200:
                    logger.error("Error enviando mensaje (status=%d): %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.error("Error HTTP enviando mensaje: %s", e)

    async def create_forum_topic(self, chat_id: str | int, name: str) -> int | None:
        """Crea un nuevo tema/hilo en un supergrupo de Telegram."""
        clean_name = name[:120].strip() or "🎯 Nueva búsqueda"

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/createForumTopic",
                    json={"chat_id": chat_id, "name": clean_name},
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    topic_id = resp.json()["result"]["message_thread_id"]
                    logger.info("Tema creado: id=%s ('%s')", topic_id, clean_name)
                    return topic_id
                logger.warning("No se pudo crear topic: %s", resp.text[:200])
            except Exception as e:
                logger.error("Error creando topic: %s", e)
        return None

    def _format_results(self, results: list) -> tuple[str, list[dict[str, Any]]]:
        """Formatea los resultados para mostrar en Telegram y devuelve datos para IA."""
        items_for_ai: list[dict[str, Any]] = []
        lines: list[str] = []

        for i, opp in enumerate(results[:8], 1):
            item = opp.item
            # Formatear precio
            if item.price > 0:
                price_fmt = f"{item.price:,.0f} €".replace(",", ".")
            else:
                price_fmt = "Consultar precio"

            # Título limpio
            title = item.title[:60] if item.title else "Sin título"

            # Detalles extra
            details = []
            if item.size_m2:
                details.append(f"{int(item.size_m2)} m²")
            if item.rooms:
                details.append(f"{item.rooms} hab")
            if item.length_m:
                details.append(f"{item.length_m:.1f} m eslora")
            if item.year_built:
                details.append(f"Año {item.year_built}")
            if item.location:
                details.append(item.location[:25])

            detail_str = f" ({', '.join(details)})" if details else ""
            provider_str = f" [{item.provider}]" if item.provider else ""

            lines.append(
                f"{i}. {title}{detail_str}\n"
                f"   {price_fmt}{provider_str}\n"
                f"   {item.url or 'Sin enlace'}"
            )

            items_for_ai.append({
                "n": i,
                "title": title,
                "price": item.price,
                "provider": item.provider,
                "url": item.url,
                "location": item.location,
                "size_m2": item.size_m2,
                "rooms": item.rooms,
                "length_m": item.length_m,
                "year_built": item.year_built,
            })

        return "\n\n".join(lines), items_for_ai

    async def process_message(self, message: dict) -> None:
        """Procesa un mensaje entrante de Telegram."""
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        thread_id = message.get("message_thread_id")

        if not text or not chat_id:
            return

        logger.info("📩 Mensaje recibido (chat=%s, thread=%s): '%s'", chat_id, thread_id, text[:80])

        # Ignorar mensajes del propio bot
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            return

        # ── Comandos ──
        if text.startswith("/start") or text.startswith("/help"):
            await self.send_message(
                chat_id,
                "🎯 ¡Hola! Soy HunterBot, tu asesor de inversiones con IA.\n\n"
                "Escríbeme lo que buscas en lenguaje natural:\n"
                '  "Quiero una parcela en Málaga por menos de 80.000€"\n'
                '  "Busca lanchas Zar Formenti de ocasión"\n'
                '  "Pisos en Barcelona centro por 200.000€"\n\n'
                "Yo haré:\n"
                "1. Abriré un tema dedicado para tu búsqueda\n"
                "2. Rastrearé portales reales (Wallapop, Pisos.com, Boat24...)\n"
                "3. Te mostraré las mejores opciones con análisis experto\n"
                "4. Podrás preguntarme sobre los resultados dentro del tema\n\n"
                "¡Escribe tu primera búsqueda!",
                thread_id,
            )
            return

        if text.startswith("/"):
            return  # Ignorar otros comandos no reconocidos

        # ── Detectar si es conversación de seguimiento ──
        is_general = not thread_id or thread_id == 1
        topic_key = f"{chat_id}:{thread_id}"

        if not is_general and topic_key in _topic_context:
            # Es un mensaje de seguimiento dentro de un tema con contexto
            await self._handle_followup(chat_id, text, thread_id, topic_key)
            return

        # ── Nueva búsqueda ──
        await self._handle_new_search(chat_id, text, thread_id, is_general)

    async def _handle_followup(self, chat_id: int, text: str, thread_id: int, topic_key: str) -> None:
        """Maneja preguntas de seguimiento dentro de un tema existente."""
        context = _topic_context.get(topic_key, "")
        logger.info("💬 Followup en tema %s: '%s'", thread_id, text[:50])

        # Detectar si quiere una nueva búsqueda o es pregunta sobre resultados
        search_words = ["busca", "encuentra", "búscame", "quiero comprar", "necesito"]
        is_new_search = any(w in text.lower() for w in search_words) and len(text) > 20

        if is_new_search:
            # Tratar como nueva búsqueda dentro del mismo tema
            await self._handle_new_search(chat_id, text, thread_id, is_general=False)
            return

        # Pregunta sobre resultados previos → usar IA conversacional
        await self.send_message(chat_id, "🤔 Analizando tu pregunta...", thread_id)

        response = await self.ai.chat_followup(text, context)
        await self.send_message(chat_id, f"💡 {response}", thread_id)

    async def _handle_new_search(self, chat_id: int, text: str, thread_id: int | None, is_general: bool) -> None:
        """Ejecuta una nueva búsqueda completa."""
        # 1. Consultar IA para interpretar la búsqueda
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

        # 2. Crear tema dedicado si estamos en General
        target_thread = thread_id
        if is_general:
            new_thread = await self.create_forum_topic(chat_id, topic_title)
            if new_thread:
                target_thread = new_thread
                await self.send_message(
                    chat_id,
                    f"🎯 He abierto el tema '{topic_title}' para tu búsqueda.\n"
                    f"👉 Entra al tema para ver los resultados.",
                    thread_id,
                )

        # 3. Publicar asesoramiento inicial
        tags_str = " ".join(tags)
        await self.send_message(
            chat_id,
            f"🧠 ASESORAMIENTO HUNTERBOT\n"
            f"🏷️ {tags_str}\n\n"
            f"💡 {advice}\n\n"
            f"🔎 Rastreando portales en tiempo real...",
            target_thread,
        )

        # 4. Ejecutar rastreo
        engine = HunterEngine(self.cfg)
        try:
            results = await engine.search_all(criteria)

            # Filtrar y ordenar
            filtered = [r for r in results if r.score >= self.cfg.opportunity_threshold]
            if not filtered and results:
                filtered = results[:6]

            if not filtered:
                query_desc = criteria.query or criteria.location or "tu búsqueda"
                no_results_msg = (
                    f"🔍 He rastreado los portales para '{query_desc}' "
                    f"pero no he detectado anuncios activos en este momento.\n\n"
                    f"💬 Puedes intentar:\n"
                    f"- Ampliar el presupuesto\n"
                    f"- Buscar en zonas cercanas\n"
                    f"- Cambiar los términos de búsqueda"
                )
                await self.send_message(chat_id, no_results_msg, target_thread)
                return

            # 5. Formatear y mostrar resultados
            results_text, items_for_ai = self._format_results(filtered)
            await self.send_message(
                chat_id,
                f"🎯 RESULTADOS ({len(filtered)} opciones encontradas):\n\n{results_text}",
                target_thread,
            )

            # 6. Pedir a la IA que ANALICE los resultados
            analysis = await self.ai.analyze_results(text, items_for_ai)
            if analysis:
                await self.send_message(
                    chat_id,
                    f"🧠 ANÁLISIS EXPERTO:\n\n{analysis}\n\n"
                    f"💬 Pregúntame lo que quieras sobre estos resultados.",
                    target_thread,
                )

            # 7. Guardar contexto para conversación de seguimiento
            topic_key = f"{chat_id}:{target_thread}"
            context_summary = (
                f"Búsqueda: '{text}'\n"
                f"Categoría: {criteria.category}\n"
                f"Resultados:\n{json.dumps(items_for_ai[:5], ensure_ascii=False, default=str)}"
            )
            _topic_context[topic_key] = context_summary[:2000]

        except Exception as e:
            logger.error("Error en búsqueda: %s", e, exc_info=True)
            await self.send_message(
                chat_id,
                "⚠️ Error al rastrear los portales. Inténtalo de nuevo en unos segundos.",
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
