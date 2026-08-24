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
        loc = (criteria.location or "espana").lower().strip()

        # Limpiar comas y provincias añadidas "Foz, Lugo" -> "foz"
        if "," in loc:
            loc = loc.split(",")[0].strip()
        loc = loc.replace(" ", "-")

        # Eliminar acentos para la URL
        replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
        for a, b in replacements.items():
            loc = loc.replace(a, b)

        prop_type = "viviendas"
        if criteria.property_types and "lands" in criteria.property_types:
            prop_type = "terrenos"
        elif criteria.property_types and "premises" in criteria.property_types:
            prop_type = "locales"
        elif criteria.query and any(w in criteria.query.lower() for w in ["terreno", "parcela", "finca", "solar"]):
            prop_type = "terrenos"

        url = f"{self.base_url}/es/{op_path}/{prop_type}/{quote(loc)}/todas-las-zonas/l"

        params: dict[str, str] = {}
        if criteria.price_min:
            params["minPrice"] = str(int(criteria.price_min))
        if criteria.price_max:
            params["maxPrice"] = str(int(criteria.price_max))

        items: list[Item] = []
        try:
            extra_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://www.google.es/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            resp = await self.http.get(
                url, params=params, rate_limit=self.default_rate_limit,
                headers=extra_headers,
            )
            if resp.status_code != 200:
                logger.warning("Fotocasa returned status %d for URL: %s", resp.status_code, url)
                return []

            parser = HTMLParser(resp.text)

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

            if not items:
                articles = parser.css("article.re-Card") or parser.css(".re-CardPackMinimal") or parser.css("[class*='re-Card']")
                for art in articles:
                    link_el = art.css_first("a.re-Card-link") or art.css_first("a[href*='/inmueble/']") or art.css_first("a")
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
