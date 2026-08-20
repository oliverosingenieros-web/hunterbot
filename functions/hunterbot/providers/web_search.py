"""Provider de búsqueda web genérica usando DuckDuckGo.

SOLO se usa como último recurso cuando los providers especializados
(Fotocasa, Pisos.com, Wallapop, etc.) no devuelven resultados.
Los resultados se filtran para excluir páginas no relevantes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)

# Dominios irrelevantes que nunca son ofertas reales
_BLOCKED_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "wiktionary.org",
    "youtube.com", "youtu.be",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "tiktok.com", "pinterest.com", "linkedin.com",
    "reddit.com",
    "google.com", "google.es",
    "elpais.com", "elmundo.es", "abc.es", "lavanguardia.com",
    "rtve.es", "antena3.com", "telecinco.es",
    "tripadvisor.com", "booking.com",
}

# Dominios que SÍ son portales de anuncios reales
_GOOD_DOMAINS = {
    "idealista.com", "fotocasa.es", "pisos.com", "habitaclia.com",
    "yaencontre.com", "tucasa.com", "enalquiler.com", "vibbo.com",
    "milanuncios.com", "wallapop.com", "amazon.es", "amazon.com",
    "topbarcos.com", "cosasdebarcos.com", "boat24.com", "yachtworld.com",
    "nautalia.com", "engel-voelkers.com", "inmobiliaria.com",
    "segundamano.es", "ebay.es", "pccomponentes.com",
}


def _is_relevant_url(url: str) -> bool:
    """Filtra URLs irrelevantes (Wikipedia, noticias, redes sociales)."""
    url_lower = url.lower()
    for blocked in _BLOCKED_DOMAINS:
        if blocked in url_lower:
            return False
    return True


def _is_good_domain(url: str) -> bool:
    """Detecta si la URL es de un portal de anuncios conocido."""
    url_lower = url.lower()
    for good in _GOOD_DOMAINS:
        if good in url_lower:
            return True
    return False


@register
class WebSearchProvider(BaseProvider):
    """Provider para búsquedas web vía DuckDuckGo.
    
    Actúa como rastreador complementario: busca en la web y filtra
    solo resultados de portales de anuncios reales.
    """

    name = "web_search"
    display_name = "Web Search (DuckDuckGo)"
    category = ItemCategory.OTHER
    requires_api_key = False
    default_rate_limit = 2.0

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Realiza una búsqueda web y extrae posibles ofertas de portales reales."""
        # Construir query orientada a portales de anuncios
        parts = []
        if criteria.query:
            parts.append(criteria.query)
        if criteria.location:
            parts.append(criteria.location)

        # Añadir contexto según categoría
        if criteria.category == ItemCategory.REAL_ESTATE:
            parts.append("comprar venta")
        elif criteria.category == ItemCategory.BOAT:
            parts.append("comprar ocasión")

        if criteria.price_max:
            parts.append(f"menos de {int(criteria.price_max)}€")

        query = " ".join(parts)
        if not query.strip():
            return []

        items: list[Item] = []
        try:
            loop = asyncio.get_running_loop()

            def _do_search() -> list[dict[str, Any]]:
                try:
                    from duckduckgo_search import DDGS
                    with DDGS() as ddgs:
                        return list(ddgs.text(query, max_results=20, region="es-es"))
                except Exception as e:
                    logger.warning("DuckDuckGo search error: %s", e)
                    return []

            results = await loop.run_in_executor(None, _do_search)

            for idx, r in enumerate(results):
                title = r.get("title", "")
                snippet = r.get("body", "")
                href = r.get("href", "")

                # FILTRO 1: Excluir URLs irrelevantes
                if not href or not _is_relevant_url(href):
                    continue

                # FILTRO 2: Priorizar portales de anuncios reales
                is_good = _is_good_domain(href)

                # Intentar parsear precio
                price = 0.0
                combined = f"{title} {snippet}"
                # Buscar formatos como "85.000 €", "120000€", "45.500 EUR"
                m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*(?:€|EUR|euros)", combined, re.IGNORECASE)
                if m:
                    try:
                        price = float(m.group(1).replace(".", "").replace(",", "."))
                    except ValueError:
                        price = 0.0

                # Solo incluir si tiene precio O es de un portal bueno
                if price > 0 or is_good:
                    items.append(
                        Item(
                            id=self._make_id(str(hash(href))),
                            provider=self.name,
                            category=criteria.category or ItemCategory.OTHER,
                            title=title[:100],
                            price=price,
                            url=href,
                            description=snippet[:200] if snippet else None,
                        )
                    )

        except Exception as e:
            logger.error("Error en Web Search: %s", e)

        logger.info("Web Search: %d resultados relevantes de %d totales", len(items), len(results) if 'results' in dir() else 0)
        return items
