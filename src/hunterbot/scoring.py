"""Motor estadístico de tasación, análisis de percentiles y scoring universal (1-10)."""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any

from hunterbot.config import HunterConfig, ScoringWeights
from hunterbot.models import Item, ItemCategory, OpportunityScore, ZoneStats

logger = logging.getLogger(__name__)


def compute_market_distribution(items: list[Item]) -> dict[str, Any]:
    """Calcula las métricas estadísticas del mercado en tiempo real para una búsqueda."""
    prices = [it.price for it in items if it.price and it.price > 50]
    if not prices:
        return {}

    prices.sort()
    n = len(prices)
    mean_val = statistics.mean(prices)
    median_val = statistics.median(prices)
    stdev_val = statistics.stdev(prices) if n > 1 else 0.0

    p25 = prices[int(n * 0.25)] if n >= 4 else prices[0]
    p75 = prices[int(n * 0.75)] if n >= 4 else prices[-1]

    return {
        "count": n,
        "mean_price": round(mean_val, 2),
        "median_price": round(median_val, 2),
        "stdev_price": round(stdev_val, 2),
        "p25_price": round(p25, 2),
        "p75_price": round(p75, 2),
        "min_price": prices[0],
        "max_price": prices[-1],
    }


class ScoringEngine:
    """Calcula la puntuación de oportunidad (1.0 a 10.0) combinando estadística real y extras técnicos."""

    def __init__(self, config: HunterConfig) -> None:
        self.config = config

    def score_all_items(
        self,
        items: list[Item],
        zone_stats: ZoneStats | None = None,
    ) -> list[OpportunityScore]:
        """Calcula el score de una lista de items utilizando la distribución estadística global de la búsqueda."""
        market_stats = compute_market_distribution(items)
        scored: list[OpportunityScore] = []

        for item in items:
            opp = self.score_item(item, zone_stats=zone_stats, market_stats=market_stats)
            scored.append(opp)

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def score_item(
        self,
        item: Item,
        zone_stats: ZoneStats | None = None,
        market_stats: dict[str, Any] | None = None,
    ) -> OpportunityScore:
        """Calcula el score de un item con detección de percentiles, extras y anomalías."""
        if item.category == ItemCategory.REAL_ESTATE:
            return self._score_real_estate(item, zone_stats, market_stats)
        elif item.category == ItemCategory.BOAT:
            return self._score_boat(item, market_stats)
        elif item.category == ItemCategory.PRODUCT:
            return self._score_product(item, market_stats)
        else:
            return self._score_generic(item, market_stats)

    def _score_real_estate(
        self,
        item: Item,
        stats: ZoneStats | None,
        market_stats: dict[str, Any] | None,
    ) -> OpportunityScore:
        weights = self.config.get_scoring_weights("real_estate")
        factors: dict[str, float] = {}
        reasons: list[str] = []

        median_ref = stats.median_price if stats and stats.median_price > 0 else (market_stats or {}).get("median_price")

        # Factor 1: Precio vs Mediana
        if median_ref and median_ref > 0 and item.price > 0:
            diff_pct = ((median_ref - item.price) / median_ref) * 100
            
            # Detección de posibles anomalías (precios excesivamente bajos que podrían ser alquileres o estafas)
            if diff_pct > 75:
                factors["price_vs_zone_avg"] = 0.5
                reasons.append("⚠️ Precio atípicamente bajo (verificar si es alquiler o proindiviso)")
            elif diff_pct >= 20:
                factors["price_vs_zone_avg"] = 0.95
                reasons.append(f"🔥 Oportunidad: {diff_pct:.0f}% por debajo de la mediana del mercado")
            elif diff_pct >= 5:
                factors["price_vs_zone_avg"] = 0.8
                reasons.append(f"{diff_pct:.0f}% por debajo de la media ({median_ref:,.0f} €)")
            elif diff_pct < -20:
                factors["price_vs_zone_avg"] = 0.35
                reasons.append(f"Precio superior a la media de la zona ({abs(diff_pct):.0f}% por encima)")
            else:
                factors["price_vs_zone_avg"] = 0.6
        else:
            factors["price_vs_zone_avg"] = 0.6

        # Factor 2: Precio por m²
        if item.price_per_m2 and item.price_per_m2 > 0:
            if item.price_per_m2 < 35:
                factors["price_per_m2"] = 0.9
                reasons.append(f"Excelente ratio suelo ({item.price_per_m2:.1f} €/m²)")
            elif item.price_per_m2 < 65:
                factors["price_per_m2"] = 0.75
            else:
                factors["price_per_m2"] = 0.5
        else:
            factors["price_per_m2"] = 0.5

        # Factor 3: Suministros y Calificación Urbanística
        f_util = 0.5
        if item.land_type and "urbano" in item.land_type.lower():
            f_util += 0.25
            reasons.append("Suelo Urbano Edificable consolidado")
        if item.utilities:
            f_util += 0.25
            reasons.append(f"Suministros confirmados ({item.utilities})")
        factors["utilities_quality"] = min(1.0, f_util)

        # Factor 4: Calidad de anuncio
        quality = 0.5
        if item.image_url:
            quality += 0.2
        if item.description and len(item.description) > 80:
            quality += 0.3
        factors["listing_quality"] = min(1.0, quality)

        w_price = weights.get("price_vs_zone_avg") or 0.35
        w_m2 = weights.get("price_per_m2") or 0.25
        w_util = weights.get("utilities_quality") or 0.25
        w_qual = weights.get("listing_quality") or 0.15

        raw_score = (
            factors["price_vs_zone_avg"] * w_price
            + factors["price_per_m2"] * w_m2
            + factors["utilities_quality"] * w_util
            + factors["listing_quality"] * w_qual
        ) * 10.0

        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_boat(
        self,
        item: Item,
        market_stats: dict[str, Any] | None,
    ) -> OpportunityScore:
        factors: dict[str, float] = {}
        reasons: list[str] = []

        median_ref = (market_stats or {}).get("median_price")

        # Factor 1: Precio vs Mediana del Modelo
        if median_ref and median_ref > 0 and item.price > 0:
            diff_pct = ((median_ref - item.price) / median_ref) * 100
            if diff_pct >= 20:
                factors["price_vs_market"] = 0.95
                reasons.append(f"🔥 Precio excepcional: {diff_pct:.0f}% inferior a la mediana ({median_ref:,.0f} €)")
            elif diff_pct >= 5:
                factors["price_vs_market"] = 0.8
                reasons.append(f"{diff_pct:.0f}% por debajo del valor medio de mercado")
            elif diff_pct < -20:
                factors["price_vs_market"] = 0.4
                reasons.append(f"Precio por encima de la media ({abs(diff_pct):.0f}% superior)")
            else:
                factors["price_vs_market"] = 0.65
        else:
            factors["price_vs_market"] = 0.6

        # Factor 2: Valor añadido técnico (Remolque, Motor 4T, Pocas Horas, Hypalon)
        bonus = 0.5
        if item.has_trailer:
            bonus += 0.2
            reasons.append("Remolque incluido (ahorro estimado 2.500 €)")
        if item.engine_hours and item.engine_hours < 350:
            bonus += 0.15
            reasons.append(f"Bajo uso de motor ({item.engine_hours} horas)")
        if item.hull_material and "hypalon" in item.hull_material.lower():
            bonus += 0.15
            reasons.append("Flotadores Hypalon-Neopreno de alta durabilidad")
        factors["technical_bonus"] = min(1.0, bonus)

        # Factor 3: Ratio eslora/precio
        if item.length_m and item.length_m > 0 and item.price > 0:
            ppm = item.price / item.length_m
            if ppm < 4500:
                factors["price_per_meter"] = 0.85
                reasons.append(f"Excelente ratio eslora/precio ({ppm:,.0f} €/m)")
            else:
                factors["price_per_meter"] = 0.55
        else:
            factors["price_per_meter"] = 0.5

        raw_score = (
            factors["price_vs_market"] * 0.45
            + factors["technical_bonus"] * 0.35
            + factors["price_per_meter"] * 0.20
        ) * 10.0

        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_product(
        self,
        item: Item,
        market_stats: dict[str, Any] | None,
    ) -> OpportunityScore:
        factors: dict[str, float] = {}
        reasons: list[str] = []

        if item.discount_percent and item.discount_percent > 0:
            f_disc = min(1.0, item.discount_percent / 50.0)
            factors["discount_percent"] = f_disc
            reasons.append(f"Descuento directo del {item.discount_percent:.0f}%")
        else:
            factors["discount_percent"] = 0.5

        if item.rating:
            factors["product_rating"] = min(1.0, max(0.0, (item.rating - 2.0) / 3.0))
            if item.rating >= 4.5:
                reasons.append(f"Excelente valoración de compradores ({item.rating}★)")
        else:
            factors["product_rating"] = 0.5

        raw_score = (factors["discount_percent"] * 0.6 + factors["product_rating"] * 0.4) * 10.0
        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_generic(
        self,
        item: Item,
        market_stats: dict[str, Any] | None,
    ) -> OpportunityScore:
        return OpportunityScore(
            item=item,
            score=6.0,
            factors={"generic": 0.6},
            reasons=["Oportunidad evaluada estándar"],
        )
