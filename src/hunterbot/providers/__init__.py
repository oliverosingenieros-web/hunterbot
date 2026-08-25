"""Registry de providers — descubrimiento y carga automática."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hunterbot.providers.base import BaseProvider

if TYPE_CHECKING:
    from hunterbot.config import HunterConfig
    from hunterbot.http_client import HunterHTTPClient

logger = logging.getLogger(__name__)

# Registry global de providers registrados
_REGISTRY: dict[str, type[BaseProvider]] = {}


def register(cls: type[BaseProvider]) -> type[BaseProvider]:
    """Decorador para registrar un provider en el registry."""
    _REGISTRY[cls.name] = cls
    logger.debug("Provider registrado: %s", cls.name)
    return cls


def get_provider_class(name: str) -> type[BaseProvider] | None:
    """Obtiene la clase de un provider por nombre."""
    return _REGISTRY.get(name)


def get_all_provider_classes() -> dict[str, type[BaseProvider]]:
    """Devuelve todos los providers registrados."""
    return dict(_REGISTRY)


def create_active_providers(
    config: HunterConfig, http_client: HunterHTTPClient
) -> list[BaseProvider]:
    """Crea instancias de todos los providers activos según la configuración.

    Solo instancia providers que estén:
    1. Registrados en el registry
    2. Habilitados en la configuración
    3. Correctamente configurados (API keys si son necesarias)
    """
    _discover_providers()

    active: list[BaseProvider] = []
    for name, cls in _REGISTRY.items():
        provider = cls(config, http_client)
        if provider.is_configured():
            active.append(provider)
            logger.info("✅ Provider activo: %s (%s)", cls.display_name, name)
        else:
            logger.debug("⏭️  Provider deshabilitado o sin configurar: %s", name)
    return active


def _discover_providers() -> None:
    """Importa todos los módulos de providers para que se auto-registren."""
    # Los imports disparan los decoradores @register
    # ruff: noqa: F401
    from hunterbot.providers import (  # type: ignore[attr-defined]
        amazon,
        boat24,
        chollometro,
        cosasdebarcos,
        fotocasa,
        idealista,
        lidl,
        pisos_com,
        thermomix,
        topbarcos,
        wallapop,
        web_search,
    )
