"""Provider para Pisos.com."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from selectolax.parser import HTMLParser

from hunterbot.models import Item, ItemCategory, Operation, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)


@register
class PisosComProvider(BaseProvider):
    """Provider para Pisos.com."""

    name = "pisos_com"
    display_name = "Pisos.com"
    category = ItemCategory.REAL_ESTATE
    requires_api_key = False
    default_rate_limit = 3.0
    base_url = "https://www.pisos.com"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca inmuebles en Pisos.com respetando el tipo de propiedad (terrenos, pisos, casas)."""
        op = "venta" if criteria.operation == Operation.SALE else "alquiler"
        loc = (criteria.location or "espana").lower().strip().replace(" ", "_")

        # Eliminar provincia si viene en formato "Foz, Lugo" -> "foz"
        if "," in loc:
            loc = loc.split(",")[0].strip()

        # Tipo de inmueble
        tipo = "pisos"
        if criteria.property_types and "lands" in criteria.property_types:
            tipo = "terrenos"
        elif criteria.property_types and "premises" in criteria.property_types:
            tipo = "locales"
        elif criteria.property_types and "homes" in criteria.property_types:
            tipo = "casas"
        elif criteria.query and any(w in criteria.query.lower() for w in ["terreno", "parcela", "finca", "solar"]):
            tipo = "terrenos"

        url = f"{self.base_url}/{op}/{tipo}-{quote(loc)}/"

        params: dict[str, str] = {}
        if criteria.price_min:
            params["pmin"] = str(int(criteria.price_min))
        if criteria.price_max:
            params["pmax"] = str(int(criteria.price_max))

        items: list[Item] = []
        try:
            resp = await self.http.get(url, params=params, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Pisos.com returned status %d for URL: %s", resp.status_code, url)
                return []

            parser = HTMLParser(resp.text)
            cards = parser.css(".ad-preview") or parser.css("[data-navigate-url]")

            for card in cards:
                nav_url = card.attributes.get("data-navigate-url") or ""
                link_el = card.css_first("a.ad-preview__title") or card.css_first("a")
                href = nav_url or (link_el.attributes.get("href", "") if link_el else "")

                title_el = card.css_first(".ad-preview__title") or card.css_first("h3")
                title = title_el.text(strip=True) if title_el else "Inmueble en Pisos.com"

                price_el = card.css_first(".ad-preview__price") or card.css_first("[class*='price']")
                price_text = price_el.text(strip=True) if price_el else ""
                price_digits = re.sub(r"[^\d]", "", price_text)
                price = float(price_digits) if price_digits else 0.0

                size_el = card.css_first(".ad-preview__characteristic--surface")
                size_val = None
                if size_el:
                    m = re.search(r"(\d+)\s*m", size_el.text(strip=True))
                    if m:
                        size_val = float(m.group(1))

                raw_id = re.search(r"/(\d+)(?:/|$|\?)", href)
                id_str = raw_id.group(1) if raw_id else str(hash(href or title))

                if href:
                    items.append(
                        Item(
                            id=self._make_id(id_str),
                            provider=self.name,
                            category=ItemCategory.REAL_ESTATE,
                            title=title,
                            price=price,
                            size_m2=size_val,
                            url=href if href.startswith("http") else f"{self.base_url}{href}",
                            location=criteria.location,
                        )
                    )
        except Exception as e:
            logger.error("Error scrapeando Pisos.com: %s", e)

        return items
