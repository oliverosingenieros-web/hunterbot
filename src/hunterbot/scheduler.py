"""Scheduler para ejecución continua y desatendida en la nube."""

from __future__ import annotations

import asyncio
import logging

from hunterbot.config import load_config
from hunterbot.engine import HunterEngine
from hunterbot.models import ItemCategory, Operation, SearchCriteria

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Búsquedas automáticas periódicas
CRON_JOBS = [
    {
        "name": "Casas / Inmuebles",
        "project": "Casa",
        "criteria": SearchCriteria(
            category=ItemCategory.REAL_ESTATE,
            location="Malaga",
            price_max=350000,
            operation=Operation.SALE,
        ),
    },
    {
        "name": "Barcos de Ocasión",
        "project": "Barco",
        "criteria": SearchCriteria(
            category=ItemCategory.BOAT,
            query="velero",
        ),
    },
]

INTERVAL_HOURS = 4  # Ejecutar cada 4 horas


async def run_loop():
    cfg = load_config("config.yaml")
    logger.info("🚀 HunterBot Scheduler iniciado en la nube.")

    while True:
        engine = HunterEngine(cfg)
        try:
            for job in CRON_JOBS:
                logger.info("🔎 Ejecutando búsqueda periódica: %s", job["name"])
                try:
                    results = await engine.search_all(
                        job["criteria"], project_name=job["project"]
                    )
                    logger.info(
                        "Encontrados %d items para %s", len(results), job["name"]
                    )
                except Exception as e:
                    logger.error("Error ejecutando job %s: %s", job["name"], e)
        finally:
            await engine.close()

        logger.info(
            "💤 Durmiendo %d horas hasta el siguiente rastreo...", INTERVAL_HOURS
        )
        await asyncio.sleep(INTERVAL_HOURS * 3600)


if __name__ == "__main__":
    asyncio.run(run_loop())
