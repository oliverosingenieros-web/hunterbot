"""Tests unitarios para el motor de scoring."""

from datetime import datetime, timezone
from hunterbot.config import HunterConfig
from hunterbot.models import Item, ItemCategory, ZoneStats
from hunterbot.scoring import ScoringEngine


def test_scoring_real_estate_cheap_item():
    config = HunterConfig()
    engine = ScoringEngine(config)

    # Inmueble significativamente más barato que la media
    item = Item(
        id="test:1",
        provider="idealista",
        category=ItemCategory.REAL_ESTATE,
        title="Piso céntrico ganga",
        price=100000.0,
        size_m2=100.0,
        url="http://test.com/1",
        location="Malaga",
    )

    stats = ZoneStats(
        zone="Malaga",
        category=ItemCategory.REAL_ESTATE,
        provider="idealista",
        avg_price=200000.0,
        median_price=190000.0,
        p25_price=150000.0,
        p75_price=240000.0,
        min_price=80000.0,
        max_price=400000.0,
        std_dev=30000.0,
        avg_price_per_m2=2000.0,
        sample_size=20,
    )

    opp = engine.score_item(item, zone_stats=stats)

    assert opp.score >= 7.0
    assert "más barato que la media" in " ".join(opp.reasons)


def test_scoring_product_with_discount():
    config = HunterConfig()
    engine = ScoringEngine(config)

    item = Item(
        id="test:prod1",
        provider="amazon",
        category=ItemCategory.PRODUCT,
        title="Laptop Gaming",
        price=700.0,
        original_price=1000.0,
        rating=4.8,
        url="http://amazon.es/test",
    )

    opp = engine.score_item(item)

    assert opp.score >= 7.5
    assert any("Descuento directo" in r for r in opp.reasons)
    assert any("Alta valoración" in r for r in opp.reasons)
