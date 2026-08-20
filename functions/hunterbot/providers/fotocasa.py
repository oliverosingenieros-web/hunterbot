"""Provider para Fotocasa (búsqueda y scraping ligero de datos estructurados/HTML)."""

from __future__ import annotations

import json
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
class FotocasaProvider(BaseProvider):
    """Provider para Fotocasa."""

    name = "fotocasa"
    display_name = "Fotocasa"
    category = ItemCategory.REAL_ESTATE
    requires_api_key = False
    default_rate_limit = 3.0
    base_url = "https://www.fotocasa.es"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca inmuebles en Fotocasa."""
        op_path = "comprar" if criteria.operation == Operation.SALE else "alquiler"
        loc = (criteria.location or "espana").lower().strip().replace(" ", "-")
        prop_type = "viviendas"
        if criteria.property_types and "lands" in criteria.property_types:
            prop_type = "terrenos"
        elif criteria.property_types and "premises" in criteria.property_types:
            prop_type = "locales"

        url = f"{self.base_url}/es/{op_path}/{prop_type}/{quote(loc)}/l"

        params: dict[str, str] = {}
        if criteria.price_min:
            params["minPrice"] = str(int(criteria.price_min))
        if criteria.price_max:
            params["maxPrice"] = str(int(criteria.price_max))

        items: list[Item] = []
        try:
            resp = await self.http.get(url, params=params, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Fotocasa returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)

            # Intentar extraer JSON-LD o scripts estructurados
            for script in parser.css('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.text())
                    if isinstance(data, dict) and data.get("@type") in ("ItemList", "SearchResultsPage"):
                        elements = data.get("itemListElement", [])
                        for el in elements:
                            item_data = el.get("item", el)
                            url_val = item_data.get("url") or ""
                            title_val = item_data.get("name") or "Inmueble en Fotocasa"
                            price_val = 0.0
                            offers = item_data.get("offers", {})
                            if isinstance(offers, dict):
                                price_val = float(offers.get("price", 0))

                            raw_id = re.search(r"/(\d+)(?:\?|$)", url_val)
                            id_str = raw_id.group(1) if raw_id else str(hash(url_val))

                            items.append(
                                Item(
                                    id=self._make_id(id_str),
                                    provider=self.name,
                                    category=ItemCategory.REAL_ESTATE,
                                    title=title_val,
                                    price=price_val,
                                    url=url_val if url_val.startswith("http") else f"{self.base_url}{url_val}",
                                    location=criteria.location,
                                )
                            )
                except Exception:
                    continue

            # Fallback a parseo de tarjetas HTML directas
            if not items:
                articles = parser.css("article.re-Card") or parser.css(".re-CardPackMinimal")
                for art in articles:
                    link_el = art.css_first("a.re-Card-link") or art.css_first("a")
                    price_el = art.css_first(".re-CardPrice") or art.css_first("[class*='Price']")
                    title_el = art.css_first(".re-Card-title") or art.css_first("[class*='Title']")

                    if not link_el or not price_el:
                        continue

                    href = link_el.attributes.get("href", "")
                    title = title_el.text(strip=True) if title_el else "Inmueble en Fotocasa"
                    price_text = price_el.text(strip=True)
                    price_digits = re.sub(r"[^\d]", "", price_text)
                    price = float(price_digits) if price_digits else 0.0

                    raw_id = re.search(r"/(\d+)(?:\?|$)", href)
                    id_str = raw_id.group(1) if raw_id else str(hash(href))

                    items.append(
                        Item(
                            id=self._make_id(id_str),
                            provider=self.name,
                            category=ItemCategory.REAL_ESTATE,
                            title=title,
                            price=price,
                            url=href if href.startswith("http") else f"{self.base_url}{href}",
                            location=criteria.location,
                        )
                    )
        except Exception as e:
            logger.error("Error scrapeando Fotocasa: %s", e)

        return items
