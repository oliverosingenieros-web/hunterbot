"""Provider para Amazon (búsqueda de productos)."""

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
class AmazonProvider(BaseProvider):
    """Provider para Amazon."""

    name = "amazon"
    display_name = "Amazon"
    category = ItemCategory.PRODUCT
    requires_api_key = False
    default_rate_limit = 4.0
    base_url = "https://www.amazon.es"

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Busca productos en Amazon."""
        query = criteria.query or ""
        if not query:
            return []

        domain = (
            self.provider_config.get("domain") if self.provider_config else None
        ) or "amazon.es"
        url = f"https://www.{domain}/s?k={quote_plus(query)}"

        items: list[Item] = []
        try:
            resp = await self.http.get(url, rate_limit=self.default_rate_limit)
            if resp.status_code != 200:
                logger.warning("Amazon returned status %d", resp.status_code)
                return []

            parser = HTMLParser(resp.text)
            cards = self.css_from_config(parser, "card")
            if not cards:
                cards = parser.css('[data-component-type="s-search-result"]')

            for card in cards:
                asin = card.attributes.get("data-asin") or ""
                if not asin:
                    continue

                title_el = self.css_first_from_config(card, "title") or card.css_first("h2 a span") or card.css_first("h2")
                title = title_el.text(strip=True) if title_el else "Producto Amazon"

                link_el = self.css_first_from_config(card, "link") or card.css_first("h2 a")
                href = link_el.attributes.get("href") or "" if link_el else f"/dp/{asin}"
                full_url = (
                    f"https://www.{domain}{href}" if href.startswith("/") else href
                )

                # Precios
                price_whole = self.css_first_from_config(card, "price_whole") or card.css_first(".a-price-whole")
                price_fraction = self.css_first_from_config(card, "price_fraction") or card.css_first(".a-price-fraction")
                price = 0.0
                if price_whole:
                    whole = re.sub(r"[^\d]", "", price_whole.text(strip=True))
                    frac = (
                        re.sub(r"[^\d]", "", price_fraction.text(strip=True))
                        if price_fraction
                        else "00"
                    )
                    try:
                        price = float(f"{whole}.{frac}")
                    except ValueError:
                        price = 0.0

                # Precio original (si hay descuento)
                orig_price_el = self.css_first_from_config(card, "original_price") or card.css_first(
                    ".a-price.a-text-price .a-offscreen"
                ) or card.css_first(".a-text-price")
                original_price = None
                if orig_price_el:
                    orig_digits = re.sub(
                        r"[^\d,.]", "", orig_price_el.text(strip=True)
                    ).replace(",", ".")
                    try:
                        original_price = float(orig_digits)
                    except ValueError:
                        pass

                # Rating
                rating_el = self.css_first_from_config(card, "rating") or card.css_first(
                    "i.a-icon-star-small span"
                ) or card.css_first(".a-icon-alt")
                rating = None
                if rating_el:
                    m = re.search(r"(\d+[\.,]?\d*)", rating_el.text(strip=True))
                    if m:
                        try:
                            rating = float(m.group(1).replace(",", "."))
                        except ValueError:
                            pass

                # Imagen
                img_el = self.css_first_from_config(card, "image") or card.css_first("img.s-image")
                img_url = (img_el.attributes.get("src") or "") if img_el else None

                items.append(
                    Item(
                        id=self._make_id(asin),
                        provider=self.name,
                        category=ItemCategory.PRODUCT,
                        title=title,
                        price=price,
                        url=full_url,
                        rating=rating,
                        original_price=original_price,
                        image_url=img_url,
                    )
                )
        except Exception as e:
            logger.error("Error buscando en Amazon: %s", e)

        return items
