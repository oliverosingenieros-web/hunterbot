"""Motor de orquestación y búsqueda multi-provider."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from hunterbot.analyzer import PriceAnalyzer
from hunterbot.config import HunterConfig
from hunterbot.database import Database
from hunterbot.http_client import HunterHTTPClient
from hunterbot.models import Item, ItemCategory, OpportunityScore, SearchCriteria, ZoneStats
from hunterbot.providers import create_active_providers
from hunterbot.providers.base import BaseProvider
from hunterbot.scoring import ScoringEngine

logger = logging.getLogger(__name__)


class HunterEngine:
    """Orquesta las búsquedas, guardado en base de datos y scoring."""

    def __init__(self, config: HunterConfig) -> None:
        self.config = config
        self.db = Database(config.database_path)
        self.db.connect()
        self.http = HunterHTTPClient(respect_robots=config.respect_robots_txt)
        self.scoring = ScoringEngine(config)
        self.providers: list[BaseProvider] = create_active_providers(config, self.http)

    async def close(self) -> None:
        """Cierra conexiones."""
        await self.http.close()
        self.db.close()

    async def search_all(
        self,
        criteria: SearchCriteria,
        project_name: str | None = None,
    ) -> list[OpportunityScore]:
        """Ejecuta la búsqueda en todos los providers coincidentes en paralelo."""
        target_providers = self.providers
        if criteria.provider and criteria.provider != "all":
            target_providers = [p for p in self.providers if p.name == criteria.provider]

        if criteria.category:
            target_providers = [
                p for p in target_providers
                if p.category == criteria.category or p.category == ItemCategory.OTHER
            ]

        if not target_providers:
            logger.warning("No hay providers activos para la búsqueda (categoría=%s)", criteria.category)
            return []

        logger.info(
            "Lanzando búsqueda en %d providers: %s",
            len(target_providers),
            [p.name for p in target_providers],
        )

        # Ejecutar en paralelo, capturando excepciones individuales
        tasks = [p.search(criteria) for p in target_providers]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[Item] = []
        for i, res in enumerate(results_nested):
            if isinstance(res, Exception):
                logger.error(
                    "Error en provider '%s': %s",
                    target_providers[i].name,
                    res,
                )
            elif isinstance(res, list):
                all_items.extend(res)

        logger.info("Total items encontrados: %d", len(all_items))

        if not all_items:
            return []

        # 1. Guardar en SQLite y registrar historial
        try:
            self.db.upsert_items(all_items)
            self.db.log_search(
                {"query": criteria.query, "category": str(criteria.category), "location": criteria.location},
                criteria.provider,
                len(all_items),
            )
        except Exception as e:
            logger.error("Error guardando en DB: %s", e)

        # 2. Calcular estadísticas de zona si aplica
        zone_stats: ZoneStats | None = None
        if criteria.location and criteria.category == ItemCategory.REAL_ESTATE:
            zone_stats = PriceAnalyzer.calculate_zone_stats(
                zone=criteria.location,
                category=ItemCategory.REAL_ESTATE,
                provider="aggregate",
                items=all_items,
            )
            if zone_stats:
                try:
                    self.db.save_zone_stats(
                        zone=criteria.location,
                        category=ItemCategory.REAL_ESTATE.value,
                        provider="aggregate",
                        stats=zone_stats.__dict__,
                    )
                except Exception as e:
                    logger.error("Error guardando zone stats: %s", e)

        # 3. Calcular Scoring
        scored: list[OpportunityScore] = []
        for item in all_items:
            opp = self.scoring.score_item(item, zone_stats=zone_stats)
            scored.append(opp)

        # Ordenar por score descendente
        scored.sort(key=lambda x: x.score, reverse=True)

        # 4. Sincronizar en la nube con Firestore (si está configurado)
        try:
            from hunterbot.database_firebase import FirestoreDatabase
            fs_db = FirestoreDatabase()
            if fs_db.enabled:
                for opp in scored[:10]:  # Limitar a top 10
                    if opp.score >= self.config.opportunity_threshold:
                        fs_db.save_opportunity(opp)
        except Exception:
            pass  # Firestore es opcional

        # NOTA: NO enviamos notificaciones Telegram desde el engine.
        # Las notificaciones las gestiona telegram_bot.py directamente
        # para evitar mensajes duplicados.

        return scored
