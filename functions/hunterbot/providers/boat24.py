"""Provider para Boat24.com (embarcaciones en Europa y España)."""

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
class Boat24Provider(BaseProvider):
    """Provider para Boat24."""

    name = "boat24"
    display_name = "Boat24"
    category = ItemCategory.BOAT
    requires_api_key = False
    default_rate_limit = 3.0
    base_url = "https://www.boat24.com/es"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca barcos en Boat24."""
        query = criteria.query or ""
        url = f"{self.base_url}/barcos-ocasion/"
        if query:
            url = f"{self.base_url}/barcos-ocasion/?whr={quote_plus(query)}"

        items: list[Item] = []
        try:
            resp = await self.http.get(url, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Boat24 returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)
            cards = self.css_from_config(parser, "card") or (
                parser.css(".blist__item")
                or parser.css(".row.blist")
                or parser.css("article")
            )

            for card in cards:
                link_el = self.css_first_from_config(card, "link") or card.css_first("a[href*='/detalle/']") or card.css_first("a")
                if not link_el:
                    continue

                href = link_el.attributes.get("href") or ""
                title_el = self.css_first_from_config(card, "title") or (
                    card.css_first(".blist__title")
                    or card.css_first("h3")
                    or card.css_first("h2")
                )
                title = (
                    title_el.text(strip=True) if title_el else link_el.text(strip=True)
                )

                price_el = self.css_first_from_config(card, "price") or card.css_first(".blist__price") or card.css_first(
                    "[class*='price']"
                )
                price_text = price_el.text(strip=True) if price_el else ""
                price_digits = re.sub(r"[^\d]", "", price_text)
                price = float(price_digits) if price_digits else 0.0

                text_content = card.text()
                length_m = None
                m_len = re.search(r"(\d+[\.,]?\d*)\s*m\b", text_content)
                if m_len:
                    try:
                        length_m = float(m_len.group(1).replace(",", "."))
                    except ValueError:
                        pass

                raw_id = re.search(r"/detalle/(\d+)", href)
                id_str = raw_id.group(1) if raw_id else str(hash(href))

                if href and title:
                    items.append(
                        Item(
                            id=self._make_id(id_str),
                            provider=self.name,
                            category=ItemCategory.BOAT,
                            title=title,
                            price=price,
                            length_m=length_m,
                            url=href
                            if href.startswith("http")
                            else f"https://www.boat24.com{href}",
                            location=criteria.location,
                        )
                    )
        except Exception as e:
            logger.error("Error buscando en Boat24: %s", e)

        return items
