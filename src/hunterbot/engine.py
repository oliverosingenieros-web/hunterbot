"""Motor de orquestación y búsqueda multi-provider."""

from __future__ import annotations

import asyncio
import logging

from hunterbot.analyzer import PriceAnalyzer
from hunterbot.config import HunterConfig
from hunterbot.database import Database
from hunterbot.http_client import HunterHTTPClient
from hunterbot.models import (
    Item,
    ItemCategory,
    OpportunityScore,
    SearchCriteria,
    ZoneStats,
)
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
            target_providers = [
                p for p in self.providers if p.name == criteria.provider
            ]

        if criteria.category:
            target_providers = [
                p
                for p in target_providers
                if p.category == criteria.category or p.category == ItemCategory.OTHER
            ]

        if not target_providers:
            logger.warning(
                "No hay providers activos para la búsqueda (categoría=%s)",
                criteria.category,
            )
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
            p_name = target_providers[i].name
            if isinstance(res, Exception):
                logger.error("Provider '%s' falló con excepción: %s", p_name, res)
            elif isinstance(res, list):
                logger.info("Provider '%s' devolvió %d items", p_name, len(res))
                all_items.extend(res)
            else:
                logger.warning(
                    "Provider '%s' devolvió tipo inesperado: %s", p_name, type(res)
                )

        logger.info("Total items agregados de todos los providers: %d", len(all_items))

        if not all_items:
            return []

        # 1. Guardar en SQLite y registrar historial
        try:
            self.db.upsert_items(all_items)
            self.db.log_search(
                {
                    "query": criteria.query,
                    "category": str(criteria.category),
                    "location": criteria.location,
                },
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

        # 3. Calcular Scoring con distribución estadística real de mercado
        scored = self.scoring.score_all_items(all_items, zone_stats=zone_stats)

        # 4. Sincronizar en tiempo real con Cloud Firestore para alimentar Netlify
        try:
            from hunterbot.database_firebase import FirestoreDatabase

            fs_db = FirestoreDatabase()
            if fs_db.enabled:
                for opp in scored[:12]:
                    fs_db.save_opportunity(opp)
                logger.info(
                    "🔥 %d oportunidades sincronizadas con Firestore para Netlify",
                    len(scored[:12]),
                )
        except Exception as e:
            logger.warning("Error sincronizando con Firestore: %s", e)

        return scored
