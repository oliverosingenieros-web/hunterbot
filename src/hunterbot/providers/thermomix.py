"""Provider para Thermomix (Vorwerk)."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register
from hunterbot.providers.web_search import extract_price

logger = logging.getLogger(__name__)


@register
class ThermomixProvider(BaseProvider):
    """Provider para Thermomix a través de Bing Search."""

    name = "thermomix"
    display_name = "Thermomix (Vorwerk)"
    category = ItemCategory.PRODUCT
    requires_api_key = False
    default_rate_limit = 3.0
    base_url = "https://www.vorwerk.com/es/es"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca productos Thermomix usando Bing Search."""
        query = criteria.query or ""
        if not query:
            return []

        search_query = quote_plus(f"site:vorwerk.com/es/es {query}")
        url = f"https://www.bing.com/search?q={search_query}"

        items: list[Item] = []
        try:
            extra_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "es-ES,es;q=0.9",
            }
            resp = await self.http.get(url, headers=extra_headers, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Thermomix (Bing) returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)
            cards = parser.css(".b_algo")

            for card in cards:
                link_el = card.css_first("h2 a")
                if not link_el:
                    continue

                href = link_el.attributes.get("href", "")
                if "vorwerk.com" not in href:
                    continue

                title = link_el.text(strip=True)
                snip = card.css_first(".b_caption p")
                snippet = snip.text(strip=True) if snip else ""

                price = extract_price(title)
                if not price:
                    price = extract_price(snippet)

                items.append(
                    Item(
                        id=self._make_id(href),
                        provider=self.name,
                        category=self.category,
                        title=title,
                        price=price,
                        url=href,
                        description=snippet,
                    )
                )
        except Exception as e:
            logger.error("Error buscando en Thermomix: %s", e)

        return items
