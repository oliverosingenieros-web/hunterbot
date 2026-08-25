"""Provider para TopBarcos.com (embarcaciones)."""

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
class TopBarcosProvider(BaseProvider):
    """Provider para TopBarcos."""

    name = "topbarcos"
    display_name = "TopBarcos"
    category = ItemCategory.BOAT
    requires_api_key = False
    default_rate_limit = 3.0
    base_url = "https://www.topbarcos.com"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca barcos en TopBarcos."""
        query = criteria.query or ""
        url = f"{self.base_url}/barcos-ocasion"
        if query:
            url = f"{self.base_url}/buscar?q={quote_plus(query)}"

        items: list[Item] = []
        try:
            resp = await self.http.get(url, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("TopBarcos returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)
            cards = (
                parser.css(".barco-item")
                or parser.css("article")
                or parser.css(".listing-item")
            )

            for card in cards:
                link_el = card.css_first("a[href*='/barcos/']") or card.css_first("a")
                if not link_el:
                    continue

                href = link_el.attributes.get("href") or ""
                title_el = (
                    card.css_first(".title")
                    or card.css_first("h2")
                    or card.css_first("h3")
                )
                title = (
                    title_el.text(strip=True) if title_el else link_el.text(strip=True)
                )

                price_el = card.css_first(".price") or card.css_first(
                    "[class*='precio']"
                )
                price_text = price_el.text(strip=True) if price_el else ""
                price_digits = re.sub(r"[^\d]", "", price_text)
                price = float(price_digits) if price_digits else 0.0

                # Extraer eslora / año si están presentes
                text_content = card.text()
                length_m = None
                m_len = re.search(
                    r"(\d+[\.,]?\d*)\s*m(?:etros)?", text_content, re.IGNORECASE
                )
                if m_len:
                    try:
                        length_m = float(m_len.group(1).replace(",", "."))
                    except ValueError:
                        pass

                year_built = None
                m_year = re.search(r"\b(19\d\d|20[0-2]\d)\b", text_content)
                if m_year:
                    year_built = int(m_year.group(1))

                raw_id = re.search(r"/(\d+)", href)
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
                            year_built=year_built,
                            url=href
                            if href.startswith("http")
                            else f"{self.base_url}{href}",
                            location=criteria.location,
                        )
                    )
        except Exception as e:
            logger.error("Error buscando en TopBarcos: %s", e)

        return items
