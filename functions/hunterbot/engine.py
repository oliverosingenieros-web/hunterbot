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
from hunterbot.notifications import TelegramNotifier
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
        self.notifier = TelegramNotifier(config, self.http)
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
            logger.warning("No hay providers activos para la búsqueda")
            return []

        tasks = [p.search(criteria) for p in target_providers]
        results_nested: Sequence[list[Item]] = await asyncio.gather(*tasks, return_exceptions=False)

        all_items: list[Item] = []
        for res in results_nested:
            all_items.extend(res)

        # 1. Guardar en SQLite y registrar historial
        self.db.upsert_items(all_items)
        self.db.log_search(criteria.__dict__, criteria.provider, len(all_items))

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
                self.db.save_zone_stats(
                    zone=criteria.location,
                    category=ItemCategory.REAL_ESTATE.value,
                    provider="aggregate",
                    stats=zone_stats.__dict__,
                )

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
                for opp in scored:
                    if opp.score >= self.config.opportunity_threshold:
                        fs_db.save_opportunity(opp)
        except Exception:
            pass

        # 5. Notificar por Telegram chollos detectados
        for opp in scored:
            if opp.score >= self.config.opportunity_threshold:
                await self.notifier.notify_opportunity(opp, project_name=project_name)

        return scored
