"""Almacenamiento SQLite para items, historial de precios y búsquedas."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hunterbot.models import Item, ItemCategory, PriceDrop

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'EUR',
    url TEXT,
    location TEXT,
    latitude REAL,
    longitude REAL,
    size_m2 REAL,
    rooms INTEGER,
    bathrooms INTEGER,
    property_type TEXT,
    plot_size_m2 REAL,
    condition TEXT,
    seller TEXT,
    rating REAL,
    num_reviews INTEGER,
    original_price REAL,
    length_m REAL,
    beam_m REAL,
    year_built INTEGER,
    engine_power_hp REAL,
    engine_type TEXT,
    hull_material TEXT,
    boat_type TEXT,
    fuel_type TEXT,
    price_per_m2 REAL,
    discount_percent REAL,
    image_url TEXT,
    description TEXT,
    extra TEXT,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id),
    price REAL NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criteria TEXT NOT NULL,
    provider TEXT,
    results_count INTEGER,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zone_stats (
    zone TEXT NOT NULL,
    category TEXT NOT NULL,
    provider TEXT NOT NULL,
    avg_price REAL,
    median_price REAL,
    p25_price REAL,
    p75_price REAL,
    min_price REAL,
    max_price REAL,
    std_dev REAL,
    avg_price_per_m2 REAL,
    sample_size INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (zone, category, provider)
);

CREATE INDEX IF NOT EXISTS idx_items_provider ON items(provider);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_location ON items(location);
CREATE INDEX IF NOT EXISTS idx_items_price ON items(price);
CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_active);
CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history(item_id);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(recorded_at);
"""


class Database:
    """Gestiona la base de datos SQLite de HunterBot."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Establece la conexión y crea el schema si es necesario."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("Base de datos abierta: %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    # ─── Items ───────────────────────────────────────────────

    def upsert_item(self, item: Item) -> bool:
        """Inserta o actualiza un item. Devuelve True si es nuevo."""
        existing = self.get_item(item.id)

        if existing is None:
            self._insert_item(item)
            self._record_price(item.id, item.price)
            return True

        # Actualizar last_seen
        self.conn.execute(
            "UPDATE items SET last_seen = ?, price = ?, is_active = 1 WHERE id = ?",
            (item.last_seen.isoformat(), item.price, item.id),
        )

        # Registrar cambio de precio si cambió
        if abs(existing.price - item.price) > 0.01:
            self._record_price(item.id, item.price)
            logger.info(
                "Cambio de precio detectado: %s %.2f → %.2f",
                item.id,
                existing.price,
                item.price,
            )

        self.conn.commit()
        return False

    def upsert_items(self, items: list[Item]) -> tuple[int, int]:
        """Inserta/actualiza múltiples items. Devuelve (nuevos, actualizados)."""
        new_count = 0
        updated_count = 0
        for item in items:
            is_new = self.upsert_item(item)
            if is_new:
                new_count += 1
            else:
                updated_count += 1
        return new_count, updated_count

    def _insert_item(self, item: Item) -> None:
        self.conn.execute(
            """INSERT INTO items (
                id, provider, category, title, price, currency, url,
                location, latitude, longitude,
                size_m2, rooms, bathrooms, property_type, plot_size_m2,
                condition, seller, rating, num_reviews, original_price,
                length_m, beam_m, year_built, engine_power_hp, engine_type,
                hull_material, boat_type, fuel_type,
                price_per_m2, discount_percent,
                image_url, description, extra,
                first_seen, last_seen
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?
            )""",
            (
                item.id,
                item.provider,
                item.category.value,
                item.title,
                item.price,
                item.currency,
                item.url,
                item.location,
                item.latitude,
                item.longitude,
                item.size_m2,
                item.rooms,
                item.bathrooms,
                item.property_type,
                item.plot_size_m2,
                item.condition,
                item.seller,
                item.rating,
                item.num_reviews,
                item.original_price,
                item.length_m,
                item.beam_m,
                item.year_built,
                item.engine_power_hp,
                item.engine_type,
                item.hull_material,
                item.boat_type,
                item.fuel_type,
                item.price_per_m2,
                item.discount_percent,
                item.image_url,
                item.description,
                json.dumps(item.extra) if item.extra else None,
                item.first_seen.isoformat(),
                item.last_seen.isoformat(),
            ),
        )
        self.conn.commit()

    def get_item(self, item_id: str) -> Item | None:
        """Obtiene un item por ID."""
        row = self.conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def get_items(
        self,
        *,
        provider: str | None = None,
        category: str | None = None,
        location: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[Item]:
        """Obtiene items con filtros opcionales."""
        query = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []

        if active_only:
            query += " AND is_active = 1"
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if category:
            query += " AND category = ?"
            params.append(category)
        if location:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")
        if price_min is not None:
            query += " AND price >= ?"
            params.append(price_min)
        if price_max is not None:
            query += " AND price <= ?"
            params.append(price_max)

        query += " ORDER BY last_seen DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_items_by_zone(
        self, zone: str, category: str | None = None
    ) -> list[Item]:
        """Obtiene todos los items activos de una zona."""
        return self.get_items(location=zone, category=category, limit=500)

    def mark_inactive(self, item_ids: list[str]) -> None:
        """Marca items como inactivos (ya no aparecen en búsquedas)."""
        if not item_ids:
            return
        placeholders = ",".join("?" * len(item_ids))
        self.conn.execute(
            f"UPDATE items SET is_active = 0 WHERE id IN ({placeholders})",
            item_ids,
        )
        self.conn.commit()

    # ─── Price History ───────────────────────────────────────

    def _record_price(self, item_id: str, price: float) -> None:
        self.conn.execute(
            "INSERT INTO price_history (item_id, price) VALUES (?, ?)",
            (item_id, price),
        )
        self.conn.commit()

    def get_price_history(self, item_id: str) -> list[tuple[float, str]]:
        """Devuelve historial de precios: [(precio, fecha), ...]."""
        rows = self.conn.execute(
            "SELECT price, recorded_at FROM price_history WHERE item_id = ? ORDER BY recorded_at",
            (item_id,),
        ).fetchall()
        return [(row["price"], row["recorded_at"]) for row in rows]

    def get_price_drops(self, min_drop_percent: float = 5.0) -> list[PriceDrop]:
        """Detecta items cuyo precio actual es menor que el primer precio visto."""
        rows = self.conn.execute(
            """
            SELECT i.id, ph_first.price as first_price, i.price as current_price
            FROM items i
            JOIN (
                SELECT item_id, price,
                    ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY recorded_at ASC) as rn
                FROM price_history
            ) ph_first ON ph_first.item_id = i.id AND ph_first.rn = 1
            WHERE i.is_active = 1
              AND i.price < ph_first.price
              AND ((ph_first.price - i.price) / ph_first.price * 100) >= ?
            ORDER BY ((ph_first.price - i.price) / ph_first.price * 100) DESC
            """,
            (min_drop_percent,),
        ).fetchall()

        drops = []
        for row in rows:
            drop_pct = ((row["first_price"] - row["current_price"]) / row["first_price"]) * 100
            drops.append(
                PriceDrop(
                    item_id=row["id"],
                    old_price=row["first_price"],
                    new_price=row["current_price"],
                    drop_percent=round(drop_pct, 1),
                )
            )
        return drops

    # ─── Searches ────────────────────────────────────────────

    def log_search(
        self, criteria: dict[str, Any], provider: str | None, results_count: int
    ) -> None:
        """Registra una búsqueda ejecutada."""
        self.conn.execute(
            "INSERT INTO searches (criteria, provider, results_count) VALUES (?, ?, ?)",
            (json.dumps(criteria, default=str), provider, results_count),
        )
        self.conn.commit()

    # ─── Zone Stats ──────────────────────────────────────────

    def save_zone_stats(
        self,
        zone: str,
        category: str,
        provider: str,
        stats: dict[str, float],
    ) -> None:
        """Guarda/actualiza estadísticas de zona."""
        self.conn.execute(
            """INSERT OR REPLACE INTO zone_stats
            (zone, category, provider, avg_price, median_price, p25_price, p75_price,
             min_price, max_price, std_dev, avg_price_per_m2, sample_size, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                zone,
                category,
                provider,
                stats.get("avg_price"),
                stats.get("median_price"),
                stats.get("p25_price"),
                stats.get("p75_price"),
                stats.get("min_price"),
                stats.get("max_price"),
                stats.get("std_dev"),
                stats.get("avg_price_per_m2"),
                stats.get("sample_size", 0),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def get_zone_stats(
        self, zone: str, category: str, provider: str | None = None
    ) -> dict[str, Any] | None:
        """Obtiene estadísticas de una zona."""
        if provider:
            row = self.conn.execute(
                "SELECT * FROM zone_stats WHERE zone = ? AND category = ? AND provider = ?",
                (zone, category, provider),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM zone_stats WHERE zone = ? AND category = ? ORDER BY updated_at DESC LIMIT 1",
                (zone, category),
            ).fetchone()
        return dict(row) if row else None

    # ─── Summary ─────────────────────────────────────────────

    def get_summary(self) -> dict[str, Any]:
        """Resumen general de la base de datos."""
        total = self.conn.execute("SELECT COUNT(*) as c FROM items").fetchone()["c"]
        active = self.conn.execute(
            "SELECT COUNT(*) as c FROM items WHERE is_active = 1"
        ).fetchone()["c"]
        providers = self.conn.execute(
            "SELECT provider, COUNT(*) as c FROM items GROUP BY provider"
        ).fetchall()
        categories = self.conn.execute(
            "SELECT category, COUNT(*) as c FROM items GROUP BY category"
        ).fetchall()
        searches = self.conn.execute(
            "SELECT COUNT(*) as c FROM searches"
        ).fetchone()["c"]

        return {
            "total_items": total,
            "active_items": active,
            "by_provider": {row["provider"]: row["c"] for row in providers},
            "by_category": {row["category"]: row["c"] for row in categories},
            "total_searches": searches,
        }

    # ─── Helpers ─────────────────────────────────────────────

    def _row_to_item(self, row: sqlite3.Row) -> Item:
        """Convierte un row de SQLite a un Item."""
        extra = json.loads(row["extra"]) if row["extra"] else {}
        return Item(
            id=row["id"],
            provider=row["provider"],
            category=ItemCategory(row["category"]),
            title=row["title"],
            price=row["price"],
            currency=row["currency"] or "EUR",
            url=row["url"] or "",
            location=row["location"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            size_m2=row["size_m2"],
            rooms=row["rooms"],
            bathrooms=row["bathrooms"],
            property_type=row["property_type"],
            plot_size_m2=row["plot_size_m2"],
            condition=row["condition"],
            seller=row["seller"],
            rating=row["rating"],
            num_reviews=row["num_reviews"],
            original_price=row["original_price"],
            length_m=row["length_m"],
            beam_m=row["beam_m"],
            year_built=row["year_built"],
            engine_power_hp=row["engine_power_hp"],
            engine_type=row["engine_type"],
            hull_material=row["hull_material"],
            boat_type=row["boat_type"],
            fuel_type=row["fuel_type"],
            price_per_m2=row["price_per_m2"],
            discount_percent=row["discount_percent"],
            image_url=row["image_url"],
            description=row["description"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            extra=extra,
        )
