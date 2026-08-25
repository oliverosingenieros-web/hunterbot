"""Provider para Chollometro (rastreador en tiempo real de ofertas y mejores precios en España)."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers import register
from hunterbot.providers.base import BaseProvider

logger = logging.getLogger(__name__)


@register
class ChollometroProvider(BaseProvider):
    """Provider para Chollometro (electrónica, informática, moda, zapatillas...)."""

    name = "chollometro"
    display_name = "Chollometro"
    category = ItemCategory.PRODUCT
    requires_api_key = False
    default_rate_limit = 2.0
    base_url = "https://www.chollometro.com"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca chollos y ofertas vivas en Chollometro."""
        query = criteria.query or ""
        if not query:
            return []

        url = f"{self.base_url}/search?q={quote_plus(query)}"

        items: list[Item] = []
        try:
            extra_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "es-ES,es;q=0.9",
            }
            resp = await self.http.get(
                url, headers=extra_headers, rate_limit=self.default_rate_limit
            )
            if resp.status_code != 200:
                logger.warning("Chollometro returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)
            articles = (
                parser.css("article.thread")
                or parser.css(".thread-link")
                or parser.css("article")
            )

            for art in articles:
                title_el = (
                    art.css_first("a.thread-title--card")
                    or art.css_first(".thread-title")
                    or art.css_first("h2 a")
                    or art.css_first("h3 a")
                    or art.css_first("a")
                )
                if not title_el:
                    continue

                title = title_el.text(strip=True)
                href = title_el.attributes.get("href") or ""
                if not title or len(title) < 4:
                    continue

                # Extraer precio
                price = 0.0
                price_el = (
                    art.css_first(".threadItem-price")
                    or art.css_first(".thread-price")
                    or art.css_first("[class*='price']")
                )
                if price_el:
                    price_text = price_el.text(strip=True)
                    m = re.search(
                        r"(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,](\d{2}))?\s*€?", price_text
                    )
                    if m:
                        try:
                            raw = m.group(1).replace(".", "").replace(",", "")
                            price = float(raw)
                        except ValueError:
                            pass

                # Extraer tienda de origen (Amazon, MediaMarkt, PcComponentes, Nike, etc.)
                merchant_el = art.css_first(".merchant-name") or art.css_first(
                    ".thread-merchant"
                )
                merchant_str = (
                    f" [{merchant_el.text(strip=True)}]" if merchant_el else ""
                )

                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                id_str = str(hash(full_url))

                items.append(
                    Item(
                        id=self._make_id(id_str),
                        provider=self.name,
                        category=ItemCategory.PRODUCT,
                        title=f"{title}{merchant_str}"[:100],
                        price=price,
                        url=full_url,
                    )
                )
        except Exception as e:
            logger.error("Error buscando en Chollometro: %s", e)

        logger.info("Chollometro: %d chollos encontrados para '%s'", len(items), query)
        return items
