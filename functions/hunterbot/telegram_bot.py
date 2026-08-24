"""Bot interactivo de Telegram con IA conversacional, búsqueda y alertas recurrentes configurables."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

from hunterbot.ai_advisor import HunterAIAdvisor
from hunterbot.config import load_config
from hunterbot.database_firebase import FirestoreDatabase
from hunterbot.engine import HunterEngine
from hunterbot.models import ItemCategory, SearchCriteria

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Memoria de contexto por hilo (topic) para conversación
_topic_context: dict[str, dict[str, Any]] = {}
# Bloqueo en memoria para evitar llamadas simultáneas al mismo update_id / message_id
_processed_in_memory: set[str] = set()


def _get_portal_direct_links(category: ItemCategory, query: str | None, location: str | None) -> str:
    """Genera accesos directos con filtros precargados a los portales líderes según la categoría."""
    terms = " ".join(filter(None, [query, location])).strip()
    encoded = urllib.parse.quote_plus(terms)

    if category == ItemCategory.BOAT:
        return (
            "🚢 ACCESOS DIRECTOS A PORTALES NÁUTICOS:\n"
            f"• Subito.it Náutica (Italia): https://www.subito.it/annunci-italia/vendita/nautica/?q={encoded}\n"
            f"• CosasDeBarcos: https://www.cosasdebarcos.com/barcos/buscar/?q={encoded}\n"
            f"• TopBarcos: https://www.topbarcos.com/barcos-ocasion?palabra={encoded}\n"
            f"• Boat24: https://www.boat24.com/es/barcos-de-ocasion/?whr={encoded}\n"
            f"• Milanuncios Náutica: https://www.milanuncios.com/barcos-a-motor/{encoded}.htm\n"
            f"• Todobarco: https://todobarco.com/buscar-barcos?texto={encoded}"
        )
    elif category == ItemCategory.REAL_ESTATE:
        loc_clean = (location or "espana").lower().replace(" ", "-")
        if "," in loc_clean:
            loc_clean = loc_clean.split(",")[0].strip()
        return (
            "🏠 ACCESOS DIRECTOS A PORTALES INMOBILIARIOS:\n"
            f"• Idealista: https://www.idealista.com/buscar/venta-viviendas/{loc_clean}/?k={encoded}\n"
            f"• Fotocasa: https://www.fotocasa.es/es/comprar/terrenos/{loc_clean}/todas-las-zonas/l\n"
            f"• Pisos.com: https://www.pisos.com/venta/terrenos-{loc_clean}/\n"
            f"• Habitaclia: https://www.habitaclia.com/terrenos_y_solares-{loc_clean}.htm\n"
            f"• Milanuncios Inmobiliaria: https://www.milanuncios.com/inmobiliaria/{encoded}.htm"
        )
    else:
        # CATEGORÍA PRODUCTOS / INFORMÁTICA / DEPORTES / MODA
        return (
            "🛍️ ACCESOS DIRECTOS Y COMPARADORES DE PRECIO:\n"
            f"• Idealo (Comparador): https://www.idealo.es/precios/{encoded}.html\n"
            f"• Chollometro (Chollos): https://www.chollometro.com/search?q={encoded}\n"
            f"• PcComponentes: https://www.pccomponentes.com/buscar/?query={encoded}\n"
            f"• Amazon España: https://www.amazon.es/s?k={encoded}\n"
            f"• MediaMarkt: https://www.mediamarkt.es/es/search.html?query={encoded}\n"
            f"• Wallapop: https://es.wallapop.com/app/search?keywords={encoded}"
        )


class InteractiveTelegramBot:
    """Escucha mensajes en Telegram, los interpreta con IA, ejecuta búsquedas y gestiona alertas por hilo."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.cfg = load_config(config_path)
        self.bot_token = self.cfg.telegram.bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0
        self.ai = HunterAIAdvisor()
        self.db = FirestoreDatabase()

    async def send_message(self, chat_id: str | int, text: str, thread_id: int | None = None) -> None:
        """Envía un mensaje a Telegram en texto plano."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload: dict = {
                "chat_id": chat_id,
                "text": text[:4096],
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
            if item.price > 0:
                price_fmt = f"{item.price:,.0f} €".replace(",", ".")
            else:
                price_fmt = "Consultar precio"

            title = item.title[:75] if item.title else "Sin título"

            details = []
            if item.length_m:
                details.append(f"{item.length_m:.1f}m")
            if item.beam_m:
                details.append(f"Manga {item.beam_m:.2f}m")
            if item.engine_power_hp:
                details.append(f"{int(item.engine_power_hp)} CV")
            if item.year_built:
                details.append(f"Año {item.year_built}")
            if item.size_m2:
                details.append(f"{int(item.size_m2)} m²")
            if item.land_type:
                details.append(item.land_type)
            if item.location:
                details.append(item.location[:20])

            detail_str = f" ({', '.join(details)})" if details else ""
            provider_str = f" [{item.provider.upper()}]" if item.provider else ""

            # Añadir highlights detectados de la descripción
            hl_str = ""
            if item.highlights:
                hl_str = "\n   ✨ " + " • ".join(item.highlights[:3])

            lines.append(
                f"{i}. {title}{detail_str}\n"
                f"   💰 {price_fmt}{provider_str}{hl_str}\n"
                f"   🔗 {item.url or 'Sin enlace'}"
            )

            items_for_ai.append({
                "n": i,
                "title": title,
                "price": item.price,
                "provider": item.provider,
                "url": item.url,
                "location": item.location,
                "size_m2": item.size_m2,
                "length_m": item.length_m,
                "beam_m": item.beam_m,
                "engine_power_hp": item.engine_power_hp,
                "engine_type": item.engine_type,
                "engine_hours": item.engine_hours,
                "has_trailer": item.has_trailer,
                "year_built": item.year_built,
                "land_type": item.land_type,
                "utilities": item.utilities,
                "highlights": item.highlights,
                "description_raw": item.description,
            })

        return "\n\n".join(lines), items_for_ai

    async def _save_topic_subscription(
        self, chat_id: int, thread_id: int, criteria: SearchCriteria, interval_days: int, original_query: str
    ) -> None:
        """Guarda o actualiza una suscripción de búsqueda recurrente en Firestore para el tema actual."""
        if not self.db.enabled:
            return

        doc_id = f"{chat_id}_{thread_id}"
        doc_ref = self.db.db.collection("active_alerts").document(doc_id)
        data = {
            "chat_id": chat_id,
            "thread_id": thread_id,
            "query": criteria.query or original_query,
            "location": criteria.location,
            "category": criteria.category.value,
            "price_max": criteria.price_max,
            "interval_days": interval_days,
            "original_prompt": original_query,
            "active": True,
            "last_executed": datetime.now(timezone.utc).isoformat(),
        }
        try:
            doc_ref.set(data, merge=True)
            logger.info("Alerta recurrente guardada para thread %s (cada %d días)", thread_id, interval_days)
        except Exception as e:
            logger.error("Error guardando alerta recurrente: %s", e)

    async def _detect_and_set_recurring_alert(
        self, chat_id: int, thread_id: int, text: str, context_dict: dict[str, Any]
    ) -> bool:
        """Detecta si el usuario está pidiendo rastreo recurrente (semanal, cada 10 días, mensual...)."""
        lower = text.lower()
        interval_days = 0

        if "semanal" in lower or "cada semana" in lower or "cada 7 días" in lower or "cada 7 dias" in lower:
            interval_days = 7
        elif "cada 10 días" in lower or "cada 10 dias" in lower or "10 días" in lower or "10 dias" in lower:
            interval_days = 10
        elif "cada 15 días" in lower or "cada 15 dias" in lower or "quincenal" in lower:
            interval_days = 15
        elif "mensual" in lower or "cada mes" in lower or "cada 30 días" in lower or "cada 30 dias" in lower:
            interval_days = 30
        elif "diario" in lower or "cada día" in lower or "cada dia" in lower:
            interval_days = 1
        elif "seguir buscando" in lower or "sigue buscando" in lower or "busca recurrentemente" in lower or "avísame" in lower:
            interval_days = 7

        if interval_days > 0:
            crit_dict = context_dict.get("criteria", {})
            criteria = SearchCriteria(
                category=ItemCategory(crit_dict.get("category", "product")),
                query=crit_dict.get("query"),
                location=crit_dict.get("location"),
                price_max=crit_dict.get("price_max"),
            )
            original_query = context_dict.get("query", text)
            await self._save_topic_subscription(chat_id, thread_id, criteria, interval_days, original_query)

            await self.send_message(
                chat_id,
                f"✅ ¡Entendido! He activado el rastreo recurrente para este tema cada {interval_days} días.\n\n"
                f"Te publicaré un reporte exclusivo aquí dentro cuando haya nuevas ofertas o cambios en el mercado.\n"
                f"Para detenerlo cuando quieras, solo escribe 'detener búsqueda recurrente' aquí.",
                thread_id,
            )
            return True
        return False

    async def process_message(self, message: dict, update_id: int | None = None) -> None:
        """Procesa un mensaje entrante de Telegram con deduplicación estricta."""
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        thread_id = message.get("message_thread_id")
        message_id = message.get("message_id")

        if not text or not chat_id:
            return

        dedup_key = f"{chat_id}_{message_id}"
        if dedup_key in _processed_in_memory:
            logger.info("⏭️ Mensaje duplicado en memoria omitido: %s", dedup_key)
            return
        _processed_in_memory.add(dedup_key)

        if self.db.is_message_already_processed(update_id or 0, message_id or 0):
            logger.info("⏭️ Mensaje ya procesado en Firestore omitido: %s_%s", update_id, message_id)
            return

        logger.info("📩 Mensaje recibido (chat=%s, thread=%s): '%s'", chat_id, thread_id, text[:80])

        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            return

        if text.startswith("/start") or text.startswith("/help"):
            await self.send_message(
                chat_id,
                "🎯 ¡Hola! Soy HunterBot, tu asesor inteligente de compras e inversiones con IA.\n\n"
                "Rastreo selectivamente según lo que busques:\n"
                '• Barcos: "Lanchas Zar Formenti de ocasión" (Cosasdebarcos, Topbarcos, Boat24...)\n'
                '• Inmobiliaria: "Terrenos en Foz por menos de 50.000€" (Idealista, Fotocasa, Pisos.com...)\n'
                '• Productos / Chollos: "Zapatillas Nike Pegasus 40" o "Portátil i7 16GB" (Idealo, Chollometro, Amazon, PcComponentes...)\n\n'
                "Sólo se activarán las fuentes especializadas para tu tipo de consulta.",
                thread_id,
            )
            return

        if text.startswith("/reporte") or "dame un reporte" in text.lower() or "reporte actual" in text.lower():
            if thread_id:
                await self._generate_topic_report(chat_id, thread_id)
                return

        if text.startswith("/"):
            return

        is_general = not thread_id or thread_id == 1
        topic_key = f"{chat_id}:{thread_id}"

        if not is_general and ("detener" in text.lower() or "cancelar alerta" in text.lower() or "parar búsqueda" in text.lower()):
            if self.db.enabled:
                doc_id = f"{chat_id}_{thread_id}"
                self.db.db.collection("active_alerts").document(doc_id).update({"active": False})
            await self.send_message(chat_id, "🛑 Búsqueda recurrente desactivada para este tema.", thread_id)
            return

        # Intercepción PRIORITARIA si el mensaje contiene una URL para examinarla directamente
        url_match = re.search(r"https?://[^\s]+", text)
        if url_match:
            clean_url = url_match.group(0).rstrip(")]>\"'")
            handled = await self._handle_direct_url_analysis(chat_id, clean_url, text, thread_id)
            if handled:
                return

        if not is_general and topic_key in _topic_context:
            context_data = _topic_context[topic_key]
            is_recurrence = await self._detect_and_set_recurring_alert(chat_id, thread_id, text, context_data)
            if is_recurrence:
                return

            await self._handle_followup(chat_id, text, thread_id, context_data)
            return

        await self._handle_new_search(chat_id, text, thread_id, is_general)

    async def _handle_followup(self, chat_id: int, text: str, thread_id: int, context_data: dict[str, Any]) -> None:
        """Maneja preguntas de seguimiento dentro de un tema existente."""
        context_str = json.dumps(context_data, ensure_ascii=False)
        logger.info("💬 Followup en tema %s: '%s'", thread_id, text[:50])

        search_words = ["busca", "encuentra", "búscame", "quiero comprar", "necesito", "rastrea de nuevo"]
        is_new_search = any(w in text.lower() for w in search_words) and len(text) > 20

        if is_new_search:
            await self._handle_new_search(chat_id, text, thread_id, is_general=False)
            return

        await self.send_message(chat_id, "🤔 Analizando tu consulta con el asesor...", thread_id)
        response = await self.ai.chat_followup(text, context_str)
        reply = f"💡 {response}"
        await self.send_message(chat_id, reply, thread_id)
        self.db.log_interaction(chat_id, thread_id, text, reply, event_type="followup")

    async def _generate_topic_report(self, chat_id: int, thread_id: int) -> None:
        """Genera un reporte actualizado específico para este tema/hilo."""
        topic_key = f"{chat_id}:{thread_id}"
        context_data = _topic_context.get(topic_key, {})
        query = context_data.get("query", "tu búsqueda en este tema")

        await self.send_message(chat_id, f"📊 Generando reporte actualizado para '{query}'...", thread_id)

        crit_dict = context_data.get("criteria", {})
        criteria = SearchCriteria(
            category=ItemCategory(crit_dict.get("category", "product")),
            query=crit_dict.get("query", query),
            location=crit_dict.get("location"),
            price_max=crit_dict.get("price_max"),
        )

        engine = HunterEngine(self.cfg)
        try:
            results = await engine.search_all(criteria)
            results_text, items_for_ai = self._format_results(results[:6])
            analysis = await self.ai.analyze_results(query, items_for_ai)

            report_msg = (
                f"📋 REPORTE DE ACTUALIZACIÓN DEL TEMA:\n\n"
                f"{results_text}\n\n"
                f"🧠 BALANCE DEL ASESOR:\n{analysis}"
            )
            await self.send_message(chat_id, report_msg, thread_id)
        finally:
            await engine.close()

    async def _handle_direct_url_analysis(self, chat_id: int, url: str, user_prompt: str, thread_id: int | None) -> bool:
        """Si el usuario proporciona una URL específica, descarga la página, extrae las opciones y genera el peritaje."""
        try:
            await self.send_message(chat_id, f"🔍 Entrando directamente a examinar el catálogo en:\n{url}", thread_id)
            
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9",
            }
            async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    await self.send_message(chat_id, f"⚠️ No se pudo acceder a la página ({resp.status_code}).", thread_id)
                    return True

                html = resp.text
                parser = HTMLParser(html)
                
                # Extraer artículos/tarjetas de barcos del HTML
                extracted_items = []
                cards = parser.css(".c-pagination-item") or parser.css("article") or parser.css("li[class*='item']") or parser.css("div[class*='item']") or parser.css("div[class*='card']")
                
                base_domain = urllib.parse.urlparse(url).netloc
                scheme = urllib.parse.urlparse(url).scheme or "https"

                for card in cards:
                    t_el = card.css_first("a.enlacePrincipal") or card.css_first("h2") or card.css_first("h3") or card.css_first("a")
                    link_el = card.css_first("a.enlacePrincipal") or card.css_first("a[href]")
                    
                    if t_el and link_el:
                        title = t_el.text(strip=True)
                        if len(title) < 4 or title.lower() in ["recreo", "yates", "velero", "catalogo", "todas", "contacto"]:
                            continue
                        
                        card_text = card.text(strip=True)
                        price = extract_price(card_text)
                        
                        href = link_el.attributes.get("href", "")
                        if not href.startswith("http"):
                            href = f"{scheme}://{base_domain}{href}" if href.startswith("/") else f"{scheme}://{base_domain}/{href}"

                        # Heurística náutica avanzada para eslora y aptitud de remolque
                        m_len = re.search(r"(\d{1,2}[.,]\d{1,2})\s*(?:m|metros)?", f"{title} {card_text}")
                        m_num = re.search(r"\b(\d{3})\b", title) # Ej. Cap Ferret 522 -> 5.22m, Flyer 650 -> 6.5m
                        m_feet = re.search(r"\b(\d{2})\b", title) # Ej. 37, 41 -> pies
                        
                        length_m = None
                        is_trailerable = False
                        
                        if m_len:
                            length_m = float(m_len.group(1).replace(",", "."))
                        elif m_num:
                            d = int(m_num.group(1))
                            if 400 <= d <= 900:
                                length_m = round(d / 100.0, 2)
                        elif m_feet:
                            ft = int(m_feet.group(1))
                            if 14 <= ft <= 22:
                                length_m = round(ft * 0.3048, 2)
                            elif ft >= 28:
                                length_m = round(ft * 0.3048, 2)

                        if length_m and length_m <= 6.8:
                            is_trailerable = True
                        elif any(k in title.lower() for k in ["sundeck", "open", "semirigida", "cap ferret", "cap camarat", "quick", "zar", "522", "550", "600", "650"]):
                            is_trailerable = True
                            if not length_m:
                                length_m = 5.5

                        extracted_items.append({
                            "title": title,
                            "price": price,
                            "length_m": length_m,
                            "is_trailerable": is_trailerable,
                            "url": href,
                            "raw_text": card_text[:200]
                        })

                if not extracted_items:
                    await self.send_message(chat_id, "⚠️ No se detectaron fichas de barcos legibles en esa URL.", thread_id)
                    return True

                # Filtrar los remolcables reales según el pedido del usuario
                remolcables = [it for it in extracted_items if it["is_trailerable"]]
                if not remolcables:
                    remolcables = extracted_items[:6]

                # Formatear y enviar
                lines = [f"🚢 BARCOS IDENTIFICADOS EN {base_domain.upper()} (Filtrado: Aptos para remolque < 6.8m):\n"]
                for i, it in enumerate(remolcables[:8], 1):
                    p_str = f"{it['price']:,.0f} €".replace(",", ".") if it["price"] > 0 else "Consultar precio"
                    len_str = f" | Eslora est.: ~{it['length_m']}m" if it.get("length_m") else ""
                    lines.append(f"{i}. {it['title']}{len_str}\n   💰 {p_str}\n   🔗 {it['url']}")

                await self.send_message(chat_id, "\n\n".join(lines), thread_id)

                # Dictamen del perito naval
                analysis = await self.ai.analyze_results(user_prompt, remolcables[:6])
                if analysis:
                    report_ai = (
                        f"🧠 PERITAJE NAVAL (Barcos Remolcables):\n\n{analysis}\n\n"
                        f"💡 Nota técnica sobre remolque en España: Límite legal sin transporte especial = 2,55 m de manga y MMA del remolque según vehículo tractor (B o B96/B+E)."
                    )
                    await self.send_message(chat_id, report_ai, thread_id)
                    self.db.log_interaction(chat_id, thread_id, user_prompt, report_ai, event_type="url_analysis")

                return True
        except Exception as e:
            logger.error("Error analizando URL directa: %s", e, exc_info=True)
            return False

    async def _handle_new_search(self, chat_id: int, text: str, thread_id: int | None, is_general: bool) -> None:
        """Ejecuta una nueva búsqueda completa activando únicamente las webs especializadas para la categoría."""
        # Comprobar si el usuario envió una URL concreta para examinarla
        url_match = re.search(r"https?://[^\s]+", text)
        if url_match:
            handled = await self._handle_direct_url_analysis(chat_id, url_match.group(0), text, thread_id)
            if handled:
                return

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

        target_thread = thread_id
        if is_general:
            new_thread = await self.create_forum_topic(chat_id, topic_title)
            if new_thread:
                target_thread = new_thread
                await self.send_message(
                    chat_id,
                    f"🎯 He abierto el tema '{topic_title}' para tu búsqueda.\n"
                    f"👉 Entra al tema para ver los resultados y asesoramiento.",
                    thread_id,
                )

        # 1. Diagnóstico de mercado en el hilo
        tags_str = " ".join(tags)
        cat_label = {
            ItemCategory.BOAT: "🚢 Portales náuticos",
            ItemCategory.REAL_ESTATE: "🏠 Portales inmobiliarios",
            ItemCategory.PRODUCT: "🛍️ Comparadores y tiendas de producto (Idealo, Chollometro, Amazon...)",
        }.get(criteria.category, "🌐 Fuentes especializadas")

        await self.send_message(
            chat_id,
            f"🧠 ASESORAMIENTO EXPERTO HUNTERBOT\n"
            f"🏷️ {tags_str}\n\n"
            f"💡 Diagnóstico de Mercado:\n{advice}\n\n"
            f"🔎 Activando rastreo especializado en: {cat_label}...",
            target_thread,
        )

        # 2. Ejecución dirigida por categoría
        engine = HunterEngine(self.cfg)
        try:
            results = await engine.search_all(criteria)
            filtered = [r for r in results if r.score >= self.cfg.opportunity_threshold]
            if not filtered and results:
                filtered = results[:8]

            portal_links = _get_portal_direct_links(criteria.category, criteria.query, criteria.location)

            if not filtered:
                query_desc = criteria.query or criteria.location or "tu búsqueda"
                no_results_msg = (
                    f"🔍 RASTREO DIRECTO:\n"
                    f"No se detectaron ofertas destacadas indexadas recientemente para '{query_desc}'.\n\n"
                    f"{portal_links}\n\n"
                    f"💬 Puedes consultar los comparadores anteriores o pedirme buscar con otro modelo/marca."
                )
                await self.send_message(chat_id, no_results_msg, target_thread)
                return

            # 3. Mostrar ofertas encontradas
            results_text, items_for_ai = self._format_results(filtered)
            await self.send_message(
                chat_id,
                f"🎯 OFERTAS ENCONTRADAS ({len(filtered)} opciones):\n\n"
                f"{results_text}\n\n"
                f"{portal_links}",
                target_thread,
            )

            # 4. Análisis comparativo con IA
            analysis = await self.ai.analyze_results(text, items_for_ai)
            if analysis:
                reply_analysis = (
                    f"🧠 RECOMENDACIÓN DEL ASESOR:\n\n{analysis}\n\n"
                    f"💬 Puedes preguntarme dudas, o pedirme: 'Sigue buscando cada 7 días' para mantener este tema actualizado."
                )
                await self.send_message(
                    chat_id,
                    reply_analysis,
                    target_thread,
                )
                self.db.log_interaction(chat_id, target_thread, text, reply_analysis, event_type="new_search")

            # 5. Guardar contexto
            topic_key = f"{chat_id}:{target_thread}"
            _topic_context[topic_key] = {
                "query": text,
                "criteria": {
                    "category": criteria.category.value,
                    "query": criteria.query,
                    "location": criteria.location,
                    "price_max": criteria.price_max,
                },
                "items": items_for_ai[:6],
            }

        except Exception as e:
            logger.error("Error en búsqueda: %s", e, exc_info=True)
            await self.send_message(
                chat_id,
                "⚠️ Error al rastrear las fuentes. Inténtalo de nuevo en unos segundos.",
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
                                asyncio.create_task(self.process_message(u["message"], u.get("update_id")))
                except Exception as e:
                    logger.error("Error en loop de Telegram: %s", e)
                    await asyncio.sleep(5)


if __name__ == "__main__":
    bot = InteractiveTelegramBot()
    asyncio.run(bot.run())
