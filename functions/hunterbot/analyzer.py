"""Analizador estadístico de precios y tendencias."""

from __future__ import annotations

import statistics
from typing import Sequence

from hunterbot.models import Item, ItemCategory, ZoneStats


class PriceAnalyzer:
    """Calcula métricas de mercado para scoring y visualización."""

    @staticmethod
    def calculate_zone_stats(
        zone: str,
        category: ItemCategory,
        provider: str,
        items: Sequence[Item],
    ) -> ZoneStats | None:
        """Calcula estadísticas agregadas a partir de una lista de items."""
        valid_items = [i for i in items if i.price and i.price > 0]
        if not valid_items:
            return None

        prices = [i.price for i in valid_items]
        prices_m2 = [i.price_per_m2 for i in valid_items if i.price_per_m2]

        sorted_prices = sorted(prices)
        n = len(sorted_prices)

        median_val = statistics.median(prices)
        avg_val = statistics.mean(prices)
        std_dev = statistics.stdev(prices) if n > 1 else 0.0

        p25 = sorted_prices[int(n * 0.25)]
        p75 = sorted_prices[int(n * 0.75)]

        avg_m2 = statistics.mean(prices_m2) if prices_m2 else None

        return ZoneStats(
            zone=zone,
            category=category,
            provider=provider,
            avg_price=round(avg_val, 2),
            median_price=round(median_val, 2),
            p25_price=round(p25, 2),
            p75_price=round(p75, 2),
            min_price=round(min(prices), 2),
            max_price=round(max(prices), 2),
            std_dev=round(std_dev, 2),
            avg_price_per_m2=round(avg_m2, 2) if avg_m2 else None,
            sample_size=n,
        )
