"""Modelos de datos universales para HunterBot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ItemCategory(str, Enum):
    """Categoría del item encontrado."""

    REAL_ESTATE = "real_estate"
    PRODUCT = "product"
    BOAT = "boat"
    VEHICLE = "vehicle"
    SERVICE = "service"
    OTHER = "other"


class Operation(str, Enum):
    """Tipo de operación inmobiliaria."""

    SALE = "sale"
    RENT = "rent"


@dataclass
class Item:
    """Representa cualquier item encontrado: inmueble, producto, barco, etc."""

    id: str
    provider: str
    category: ItemCategory
    title: str
    price: float
    url: str
    currency: str = "EUR"

    # — Ubicación —
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # — Inmuebles —
    size_m2: float | None = None
    rooms: int | None = None
    bathrooms: int | None = None
    property_type: str | None = None
    plot_size_m2: float | None = None

    # — Productos / Marketplace —
    condition: str | None = None
    seller: str | None = None
    rating: float | None = None
    num_reviews: int | None = None
    original_price: float | None = None

    # — Barcos —
    length_m: float | None = None
    beam_m: float | None = None
    year_built: int | None = None
    engine_power_hp: float | None = None
    engine_type: str | None = None
    engine_hours: int | None = None
    hull_material: str | None = None
    boat_type: str | None = None
    fuel_type: str | None = None
    has_trailer: bool | None = None

    # — Inmuebles detallados —
    land_type: str | None = None
    buildable_m2: float | None = None
    utilities: str | None = None

    # — Campos calculados —
    price_per_m2: float | None = None
    discount_percent: float | None = None

    # — Timestamps —
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))

    # — Datos extra flexibles (provider-specific) —
    extra: dict[str, Any] = field(default_factory=dict)
    highlights: list[str] = field(default_factory=list)

    # — Imagen y Descripción completa del anuncio —
    image_url: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Calcula campos derivados automáticamente."""
        if self.size_m2 and self.size_m2 > 0:
            self.price_per_m2 = round(self.price / self.size_m2, 2)
        if self.original_price and self.original_price > self.price:
            self.discount_percent = round(
                ((self.original_price - self.price) / self.original_price) * 100, 1
            )


@dataclass
class SearchCriteria:
    """Criterios de búsqueda configurados por el usuario."""

    # — Generales —
    provider: str = "all"
    query: str | None = None
    category: ItemCategory | None = None
    price_min: float | None = None
    price_max: float | None = None

    # — Ubicación —
    location: str | None = None
    location_id: str | None = None
    radius_km: int | None = None

    # — Inmuebles —
    property_types: list[str] | None = None
    operation: Operation = Operation.SALE
    size_min_m2: float | None = None
    size_max_m2: float | None = None
    rooms_min: int | None = None

    # — Productos —
    condition: str | None = None

    # — Barcos —
    length_min_m: float | None = None
    length_max_m: float | None = None
    year_min: int | None = None
    engine_power_min_hp: float | None = None
    boat_types: list[str] | None = None

    # — Filtros extra (provider-specific) —
    extra_filters: dict[str, Any] = field(default_factory=dict)

    # — Paginación —
    max_pages: int = 3


@dataclass
class OpportunityScore:
    """Resultado del análisis de oportunidad para un item."""

    item: Item
    score: float
    factors: dict[str, float]
    reasons: list[str]
    percentile: float | None = None

    @property
    def label(self) -> str:
        """Etiqueta visual del score."""
        if self.score >= 8.5:
            return "🟢 CHOLLO"
        if self.score >= 7.0:
            return "🔵 BUENA OFERTA"
        if self.score >= 5.0:
            return "🟡 PRECIO JUSTO"
        return "🔴 CARO"

    @property
    def emoji(self) -> str:
        """Emoji del score."""
        if self.score >= 8.5:
            return "🟢"
        if self.score >= 7.0:
            return "🔵"
        if self.score >= 5.0:
            return "🟡"
        return "🔴"


@dataclass
class ZoneStats:
    """Estadísticas de precios para una zona/categoría."""

    zone: str
    category: ItemCategory
    provider: str
    avg_price: float
    median_price: float
    p25_price: float
    p75_price: float
    min_price: float
    max_price: float
    std_dev: float
    sample_size: int
    avg_price_per_m2: float | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PriceDrop:
    """Representa una bajada de precio detectada."""

    item_id: str
    old_price: float
    new_price: float
    drop_percent: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
