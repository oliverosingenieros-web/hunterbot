"""Provider avanzado de rastreo e indexación directa de anuncios con precios y descripciones."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import urllib.parse
import urllib.request
from typing import Any

from selectolax.parser import HTMLParser

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)

# Sitios prioritarios por vertical
BOAT_SITES = [
    "subito.it",
    "cosasdebarcos.com",
    "topbarcos.com",
    "boat24.com",
    "todobarco.com",
    "inautia.com",
    "milanuncios.com",
]

REAL_ESTATE_SITES = [
    "pisos.com",
    "fotocasa.es",
    "idealista.com",
    "habitaclia.com",
    "yaencontre.com",
]

PRODUCT_SITES = [
    "chollometro.com",
    "idealo.es",
    "pccomponentes.com",
    "amazon.es",
    "mediamarkt.es",
    "wallapop.com",
]


def unwrap_redirect_url(url: str) -> str:
    """Extrae la URL limpia real desde redirecciones de buscadores (Bing / DuckDuckGo)."""
    if "bing.com/ck/a" in url:
        m = re.search(r"u=a1([a-zA-Z0-9_-]+)", url)
        if m:
            b64 = m.group(1).replace("-", "+").replace("_", "/")
            b64 += "=" * ((4 - len(b64) % 4) % 4)
            try:
                decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass

    if "duckduckgo.com/l/?uddg=" in url:
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            return urllib.parse.unquote(m.group(1))

    return url


def extract_price(text: str) -> float:
    """Extrae precios numéricos reales desde títulos o fragmentos descriptivos."""
    if not text:
        return 0.0

    # 1. Formato estándar: "26.500 €", "26500€", "1.200.000 €"
    m1 = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d{3,7})\s*(?:€|EUR|euros?)", text, re.IGNORECASE)
    if m1:
        raw = m1.group(1).replace(".", "").replace(",", "")
        try:
            val = float(raw)
            if 10 <= val <= 50_000_000:
                return val
        except ValueError:
            pass

    # 2. Formato con símbolo previo: "€ 26.500", "€26500", "EUR 45000"
    m2 = re.search(r"(?:€|EUR)\s*(\d{1,3}(?:[.,]\d{3})+|\d{2,7})", text, re.IGNORECASE)
    if m2:
        raw = m2.group(1).replace(".", "").replace(",", "")
        try:
            val = float(raw)
            if 10 <= val <= 50_000_000:
                return val
        except ValueError:
            pass

    # 3. Formato abreviado: "35k €", "35 k", "120k"
    m3 = re.search(r"(\d{1,4})\s*k\s*(?:€|EUR|euros?)?", text, re.IGNORECASE)
    if m3:
        try:
            val = float(m3.group(1)) * 1000
            if 10 <= val <= 50_000_000:
                return val
        except ValueError:
            pass

    # 4. Formato contextual: "precio: 26500", "por 35000", "venta 125.000"
    m4 = re.search(r"(?:precio|venta|desde|por|oferta)\s*:?\s*(\d{1,3}(?:[.,]\d{3})+|\d{3,7})", text, re.IGNORECASE)
    if m4:
        raw = m4.group(1).replace(".", "").replace(",", "")
        try:
            val = float(raw)
            if 10 <= val <= 50_000_000:
                return val
        except ValueError:
            pass

    return 0.0


def extract_metadata(text: str, category: ItemCategory) -> dict[str, Any]:
    """Extrae eslora, año de construcción, metros cuadrados o especificaciones clave."""
    meta: dict[str, Any] = {}

    if category == ItemCategory.BOAT:
        # Eslora en metros (ej. "5.30 m", "5,70m", "10 metros")
        m_len = re.search(r"(\d{1,2}[\.,]\d{1,2}|\d{1,2})\s*(?:m|metros|mts|eslora)", text, re.IGNORECASE)
        if m_len:
            try:
                l_val = float(m_len.group(1).replace(",", "."))
                if 2.0 <= l_val <= 100.0:
                    meta["length_m"] = l_val
            except ValueError:
                pass

        # Año de construcción (ej. "año 2018", "del 2021", "2015")
        m_year = re.search(r"(?:año|del|de)?\s*(20[0-2]\d|199\d)", text, re.IGNORECASE)
        if m_year:
            meta["year_built"] = int(m_year.group(1))

    elif category == ItemCategory.REAL_ESTATE:
        # Metros cuadrados (ej. "1.500 m2", "85 m²")
        m_sq = re.search(r"(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(?:m2|m²|metros cuadrados)", text, re.IGNORECASE)
        if m_sq:
            try:
                s_val = float(m_sq.group(1).replace(".", "").replace(",", ""))
                meta["size_m2"] = s_val
            except ValueError:
                pass

        # Habitaciones
        m_hab = re.search(r"(\d{1,2})\s*(?:hab|habitaciones|dormitorios)", text, re.IGNORECASE)
        if m_hab:
            meta["rooms"] = int(m_hab.group(1))

    return meta


@register
class WebSearchProvider(BaseProvider):
    """Rastreador de alta precisión que extrae anuncios reales con descripciones y precios limpios."""

    name = "web_search"
    display_name = "Rastreador Multi-Portal"
    category = ItemCategory.OTHER
    requires_api_key = False
    default_rate_limit = 1.0

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca anuncios con consultas optimizadas y extrae datos limpios."""
        terms = [criteria.query or ""]
        if criteria.location:
            terms.append(criteria.location)
        base_q = " ".join(filter(None, terms)).strip()
        if not base_q:
            return []

        # Construir lista de queries dirigidas por portal para mayor cobertura
        target_sites = []
        if criteria.category == ItemCategory.BOAT:
            target_sites = BOAT_SITES[:3]
        elif criteria.category == ItemCategory.REAL_ESTATE:
            target_sites = REAL_ESTATE_SITES[:3]
        else:
            target_sites = PRODUCT_SITES[:3]

        loop = asyncio.get_running_loop()

        def _fetch_all_sites() -> list[Item]:
            items: list[Item] = []
            seen_urls: set[str] = set()

            for site in target_sites:
                query = f"site:{site} {base_q}"
                encoded = urllib.parse.quote_plus(query)
                url = f"https://www.bing.com/search?q={encoded}"

                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"
                            ),
                            "Accept-Language": "es-ES,es;q=0.9",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        html = resp.read().decode("utf-8", errors="replace")
                        parser = HTMLParser(html)
                        cards = parser.css(".b_algo")

                        for card in cards:
                            link_el = card.css_first("h2 a")
                            if not link_el:
                                continue

                            raw_title = link_el.text(strip=True)
                            raw_url = link_el.attributes.get("href", "")
                            clean_url = unwrap_redirect_url(raw_url)

                            if clean_url in seen_urls:
                                continue
                            seen_urls.add(clean_url)

                            desc_el = card.css_first(".b_caption p") or card.css_first("p")
                            snippet = desc_el.text(strip=True) if desc_el else ""

                            combined_text = f"{raw_title} {snippet}"
                            portal_name = site.split(".")[0]

                            price = extract_price(combined_text)
                            meta = extract_metadata(combined_text, criteria.category)

                            clean_title = re.sub(
                                r"\s*[-|–]\s*(?:Cosas de Barcos|TopBarcos|Milanuncios|Pisos\.com|Fotocasa|Idealista|Chollometro|Amazon).*",
                                "",
                                raw_title,
                                flags=re.IGNORECASE,
                            ).strip()

                            if len(clean_title) < 4:
                                continue

                            items.append(
                                Item(
                                    id=self._make_id(clean_url or clean_title),
                                    provider=portal_name,
                                    category=criteria.category,
                                    title=clean_title,
                                    price=price,
                                    url=clean_url,
                                    description=snippet[:300],
                                    length_m=meta.get("length_m"),
                                    year_built=meta.get("year_built"),
                                    size_m2=meta.get("size_m2"),
                                    rooms=meta.get("rooms"),
                                    location=criteria.location or "España",
                                )
                            )
                except Exception as e:
                    logger.debug("Error consultando site:%s: %s", site, e)

            return items

        items = await loop.run_in_executor(None, _fetch_all_sites)
        logger.info("Rastreador web: %d anuncios extraídos para '%s'", len(items), base_q)
        return items
