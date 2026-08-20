"""Motor de scoring universal de oportunidades (1-10)."""

from __future__ import annotations

import logging
from typing import Any

from hunterbot.config import HunterConfig, ScoringWeights
from hunterbot.models import Item, ItemCategory, OpportunityScore, ZoneStats

logger = logging.getLogger(__name__)


class ScoringEngine:
    """Calcula la puntuación de oportunidad (1.0 a 10.0) de un item."""

    def __init__(self, config: HunterConfig) -> None:
        self.config = config

    def score_item(
        self,
        item: Item,
        zone_stats: ZoneStats | None = None,
        category_stats: dict[str, Any] | None = None,
    ) -> OpportunityScore:
        """Calcula el score de un item en función de su categoría."""
        if item.category == ItemCategory.REAL_ESTATE:
            return self._score_real_estate(item, zone_stats)
        elif item.category == ItemCategory.PRODUCT:
            return self._score_product(item, category_stats)
        elif item.category == ItemCategory.BOAT:
            return self._score_boat(item, category_stats)
        else:
            return self._score_generic(item, category_stats)

    def _score_real_estate(
        self, item: Item, stats: ZoneStats | None
    ) -> OpportunityScore:
        weights = self.config.get_scoring_weights("real_estate")
        factors: dict[str, float] = {}
        reasons: list[str] = []

        # Factor 1: Precio vs Media de la Zona
        if stats and stats.median_price > 0 and item.price > 0:
            diff_pct = ((stats.median_price - item.price) / stats.median_price) * 100
            # Si el precio es menor a la mediana, score alto
            f_price = min(1.0, max(0.0, 0.5 + (diff_pct / 100.0)))
            factors["price_vs_zone_avg"] = f_price
            if diff_pct > 15:
                reasons.append(f"{diff_pct:.1f}% más barato que la media de la zona")
            elif diff_pct < -15:
                reasons.append(f"{abs(diff_pct):.1f}% más caro que la media")
        else:
            factors["price_vs_zone_avg"] = 0.5

        # Factor 2: Precio por m²
        if stats and stats.avg_price_per_m2 and item.price_per_m2:
            diff_m2 = ((stats.avg_price_per_m2 - item.price_per_m2) / stats.avg_price_per_m2) * 100
            f_m2 = min(1.0, max(0.0, 0.5 + (diff_m2 / 100.0)))
            factors["price_per_m2"] = f_m2
            if diff_m2 > 15:
                reasons.append(f"{diff_m2:.1f}% mejor precio/m² que la media ({item.price_per_m2:.0f} €/m²)")
        elif item.price_per_m2:
            factors["price_per_m2"] = 0.5
        else:
            factors["price_per_m2"] = 0.4

        # Factor 3: Días en mercado / Reducción
        if item.discount_percent and item.discount_percent > 0:
            f_red = min(1.0, item.discount_percent / 30.0)
            factors["price_reduction"] = f_red
            reasons.append(f"Bajada de precio del {item.discount_percent:.1f}%")
        else:
            factors["price_reduction"] = 0.5

        # Factor 4: Calidad de anuncio
        quality = 0.5
        if item.image_url:
            quality += 0.2
        if item.description and len(item.description) > 100:
            quality += 0.3
        factors["listing_quality"] = min(1.0, quality)

        # Calcular Score Ponderado
        w_price = weights.get("price_vs_zone_avg") or 0.35
        w_m2 = weights.get("price_per_m2") or 0.25
        w_red = weights.get("price_reduction") or 0.25
        w_qual = weights.get("listing_quality") or 0.15

        raw_score = (
            factors["price_vs_zone_avg"] * w_price
            + factors["price_per_m2"] * w_m2
            + factors["price_reduction"] * w_red
            + factors["listing_quality"] * w_qual
        ) * 10.0

        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_product(
        self, item: Item, category_stats: dict[str, Any] | None
    ) -> OpportunityScore:
        weights = self.config.get_scoring_weights("products")
        factors: dict[str, float] = {}
        reasons: list[str] = []

        # Descuento
        if item.discount_percent and item.discount_percent > 0:
            f_disc = min(1.0, item.discount_percent / 50.0)
            factors["discount_percent"] = f_disc
            reasons.append(f"Descuento directo del {item.discount_percent:.1f}%")
        else:
            factors["discount_percent"] = 0.4

        # Rating
        if item.rating:
            f_rating = min(1.0, max(0.0, (item.rating - 2.0) / 3.0))
            factors["product_rating"] = f_rating
            if item.rating >= 4.5:
                reasons.append(f"Alta valoración ({item.rating}★)")
        else:
            factors["product_rating"] = 0.5

        # Comparativa
        factors["price_vs_category_avg"] = 0.5

        w_disc = weights.get("discount_percent") or 0.40
        w_rat = weights.get("product_rating") or 0.30
        w_avg = weights.get("price_vs_category_avg") or 0.30

        raw_score = (
            factors["discount_percent"] * w_disc
            + factors["product_rating"] * w_rat
            + factors["price_vs_category_avg"] * w_avg
        ) * 10.0

        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_boat(
        self, item: Item, category_stats: dict[str, Any] | None
    ) -> OpportunityScore:
        factors: dict[str, float] = {}
        reasons: list[str] = []

        # Precio por metro de eslora
        if item.length_m and item.length_m > 0 and item.price > 0:
            ppm = item.price / item.length_m
            # Normalización orientativa (ej. barcos de recreo ~3000-8000 €/m)
            if ppm < 4000:
                f_ppm = 0.8
                reasons.append(f"Buen ratio precio/eslora ({ppm:.0f} €/m)")
            else:
                f_ppm = 0.5
            factors["price_per_meter"] = f_ppm
        else:
            factors["price_per_meter"] = 0.5

        if item.year_built and item.year_built >= 2018:
            factors["age_value"] = 0.8
            reasons.append(f"Embarcación reciente ({item.year_built})")
        else:
            factors["age_value"] = 0.5

        raw_score = (factors["price_per_meter"] * 0.6 + factors["age_value"] * 0.4) * 10.0
        final_score = round(min(10.0, max(1.0, raw_score)), 1)
        return OpportunityScore(item=item, score=final_score, factors=factors, reasons=reasons)

    def _score_generic(
        self, item: Item, category_stats: dict[str, Any] | None
    ) -> OpportunityScore:
        return OpportunityScore(
            item=item,
            score=6.0,
            factors={"generic": 0.6},
            reasons=["Oportunidad evaluada estándar"],
        )
