"""Provider de búsqueda web genérica usando DuckDuckGo."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from duckduckgo_search import DDGS

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)


@register
class WebSearchProvider(BaseProvider):
    """Provider para búsquedas web vía DuckDuckGo."""

    name = "web_search"
    display_name = "Web Search (DuckDuckGo)"
    category = ItemCategory.OTHER
    requires_api_key = False
    default_rate_limit = 2.0

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Realiza una búsqueda web y extrae posibles ofertas."""
        query = criteria.query or ""
        if not query and criteria.location:
            query = f"ofertas {criteria.location}"
        if not query:
            return []

        items: list[Item] = []
        try:
            # duckduckgo_search es sincrono o thread-blocking, lo corremos en executor
            loop = asyncio.get_running_loop()

            def _do_search() -> list[dict[str, Any]]:
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=15, region="es-es"))

            results = await loop.run_in_executor(None, _do_search)

            for idx, r in enumerate(results):
                title = r.get("title", "Resultado Web")
                snippet = r.get("body", "")
                href = r.get("href", "")

                # Intentar parsear precio en el snippet o título (ej. "150 €", "150€", "150.00 EUR")
                price = 0.0
                m = re.search(r"(\d+[\.,]?\d*)\s*(?:€|EUR|euros)", f"{title} {snippet}", re.IGNORECASE)
                if m:
                    try:
                        price = float(m.group(1).replace(".", "").replace(",", "."))
                    except ValueError:
                        price = 0.0

                items.append(
                    Item(
                        id=self._make_id(str(hash(href or f"{title}_{idx}"))),
                        provider=self.name,
                        category=criteria.category or ItemCategory.OTHER,
                        title=title,
                        price=price,
                        url=href,
                        description=snippet,
                    )
                )
        except Exception as e:
            logger.error("Error en Web Search: %s", e)

        return items
