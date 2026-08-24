"""Provider de búsqueda web especializada y scraping libre para portales náuticos e inmobiliarios.

Usa el endpoint directo de HTML con dorks específicos hacia los principales
portales náuticos (Cosasdebarcos, Topbarcos, Boat24, Milanuncios, Todobarco, Inautia)
y portales inmobiliarios para esquivar los bloqueos de Cloudflare y obtener anuncios reales.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import urllib.request
from urllib.parse import parse_qs, urlparse
from typing import Any

from selectolax.parser import HTMLParser

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)

# Dominios de barcos prioritarios
BOAT_PORTALS = [
    "cosasdebarcos.com",
    "topbarcos.com",
    "boat24.com",
    "milanuncios.com",
    "todobarco.com",
    "inautia.com",
    "youboat.com",
    "yachtworld.com",
]

# Dominios inmobiliarios prioritarios
REAL_ESTATE_PORTALS = [
    "idealista.com",
    "fotocasa.es",
    "pisos.com",
    "habitaclia.com",
    "yaencontre.com",
    "milanuncios.com",
]


@register
class WebSearchProvider(BaseProvider):
    """Provider especializado que indexa ofertas reales desde portales líderes."""

    name = "web_search"
    display_name = "Rastreador Náutico & Inmobiliario"
    category = ItemCategory.OTHER
    requires_api_key = False
    default_rate_limit = 1.0

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Realiza una búsqueda dirigida con dorks hacia portales relevantes."""
        query_terms = []
        if criteria.query:
            query_terms.append(criteria.query)
        if criteria.location:
            query_terms.append(criteria.location)

        base_q = " ".join(query_terms).strip()
        if not base_q:
            return []

        # Construir consulta con portales prioritarios
        if criteria.category == ItemCategory.BOAT:
            site_filter = " OR ".join([f"site:{p}" for p in BOAT_PORTALS[:5]])
            full_query = f"{base_q} ({site_filter})"
        elif criteria.category == ItemCategory.REAL_ESTATE:
            site_filter = " OR ".join([f"site:{p}" for p in REAL_ESTATE_PORTALS[:4]])
            full_query = f"{base_q} ({site_filter})"
        else:
            full_query = f"{base_q} (site:milanuncios.com OR site:wallapop.com OR site:amazon.es)"

        loop = asyncio.get_running_loop()

        def _fetch_listings() -> list[Item]:
            items: list[Item] = []
            try:
                encoded = urllib.parse.quote_plus(full_query)
                url = f"https://html.duckduckgo.com/html/?q={encoded}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "es-ES,es;q=0.9",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
                    parser = HTMLParser(html)
                    results = parser.css(".result")

                    for r in results:
                        title_el = r.css_first(".result__title a")
                        snippet_el = r.css_first(".result__snippet")
                        if not title_el:
                            continue

                        raw_href = title_el.attributes.get("href", "")
                        real_url = raw_href
                        if "uddg=" in raw_href:
                            parsed_u = urlparse(raw_href)
                            qs = parse_qs(parsed_u.query)
                            if "uddg" in qs:
                                real_url = qs["uddg"][0]

                        # Evitar páginas de anuncios genéricos / publicidad de DDG
                        if "duckduckgo.com/y.js" in real_url or "bing.com" in real_url:
                            continue

                        title = title_el.text(strip=True)
                        snippet = snippet_el.text(strip=True) if snippet_el else ""

                        # Detectar portal de procedencia
                        provider_name = "portal_nautico"
                        domain_match = urlparse(real_url).netloc.lower()
                        for p in BOAT_PORTALS + REAL_ESTATE_PORTALS:
                            if p in domain_match:
                                provider_name = p.replace(".com", "").replace(".es", "")
                                break

                        # Extraer precio si está presente
                        price = 0.0
                        combined = f"{title} {snippet}"
                        m_price = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*(?:€|EUR|euros)", combined, re.IGNORECASE)
                        if m_price:
                            try:
                                price = float(m_price.group(1).replace(".", "").replace(",", "."))
                            except ValueError:
                                pass

                        # Extraer eslora / dimensiones si es barco
                        length_m = None
                        m_len = re.search(r"(\d+[\.,]?\d*)\s*m\b", combined)
                        if m_len:
                            try:
                                length_m = float(m_len.group(1).replace(",", "."))
                            except ValueError:
                                pass

                        # Extraer año
                        year = None
                        m_yr = re.search(r"\b(19\d\d|20[0-2]\d)\b", combined)
                        if m_yr:
                            try:
                                year = int(m_yr.group(1))
                            except ValueError:
                                pass

                        items.append(
                            Item(
                                id=self._make_id(str(hash(real_url))),
                                provider=provider_name,
                                category=criteria.category,
                                title=title[:100],
                                price=price,
                                length_m=length_m,
                                year_built=year,
                                url=real_url,
                                description=snippet[:300] if snippet else None,
                            )
                        )
            except Exception as e:
                logger.error("Error en WebSearchProvider: %s", e)

            return items

        results = await loop.run_in_executor(None, _fetch_listings)
        logger.info("WebSearchProvider: %d anuncios obtenidos para '%s'", len(results), full_query)
        return results
