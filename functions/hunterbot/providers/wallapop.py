"""Provider para Wallapop (vía API interna de búsqueda)."""

from __future__ import annotations

import logging
from typing import Any

from hunterbot.models import Item, ItemCategory, SearchCriteria
from hunterbot.providers.base import BaseProvider
from hunterbot.providers import register

logger = logging.getLogger(__name__)


@register
class WallapopProvider(BaseProvider):
    """Provider para Wallapop."""

    name = "wallapop"
    display_name = "Wallapop"
    category = ItemCategory.PRODUCT
    requires_api_key = False
    default_rate_limit = 2.0
    base_url = "https://api.wallapop.com/api/v3/general/search"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca productos en Wallapop."""
        query = criteria.query or criteria.location or ""
        if not query:
            return []

        params: dict[str, Any] = {
            "keywords": query,
            "order_by": "most_relevance",
        }

        if criteria.price_min is not None:
            params["min_sale_price"] = int(criteria.price_min)
        if criteria.price_max is not None:
            params["max_sale_price"] = int(criteria.price_max)

        headers = {
            "Accept": "application/json",
            "X-DeviceOS": "0",
        }

        items: list[Item] = []
        try:
            resp = await self.http.get(self.base_url, params=params, headers=headers, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Wallapop API returned status %d", resp.status_code)
                return []

            data = resp.json()
            search_objects = data.get("search_objects", [])

            for obj in search_objects:
                item_id = self._make_id(str(obj.get("id", "")))
                price_data = obj.get("price", {})
                price = float(price_data.get("amount", 0.0) if isinstance(price_data, dict) else (obj.get("price") or 0.0))
                currency = price_data.get("currency", "EUR") if isinstance(price_data, dict) else "EUR"

                web_slug = obj.get("web_slug", "")
                url = f"https://es.wallapop.com/item/{web_slug}" if web_slug else f"https://es.wallapop.com/item/{obj.get('id')}"

                images = obj.get("images", [])
                image_url = images[0].get("original") if images and isinstance(images[0], dict) else None

                items.append(
                    Item(
                        id=item_id,
                        provider=self.name,
                        category=ItemCategory.PRODUCT,
                        title=obj.get("title", "Artículo Wallapop"),
                        price=price,
                        currency=currency,
                        url=url,
                        location=obj.get("location", {}).get("city"),
                        description=obj.get("description"),
                        image_url=image_url,
                        seller=obj.get("user", {}).get("micro_name"),
                    )
                )
        except Exception as e:
            logger.error("Error buscando en Wallapop: %s", e)

        return items
