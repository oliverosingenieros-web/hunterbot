"""Interfaz abstracta para todos los providers de datos."""

from __future__ import annotations

from abc import ABC, abstractmethod

from hunterbot.config import HunterConfig, ProviderConfig
from hunterbot.http_client import HunterHTTPClient
from hunterbot.models import Item, ItemCategory, SearchCriteria


class BaseProvider(ABC):
    """Clase base para todos los providers de búsqueda.

    Cada provider debe implementar `search()` y opcionalmente `get_detail()`.
    """

    # Subclases deben definir estos atributos
    name: str = ""
    display_name: str = ""
    category: ItemCategory = ItemCategory.OTHER
    requires_api_key: bool = False
    default_rate_limit: float = 2.0
    base_url: str = ""

    def __init__(self, config: HunterConfig, http_client: HunterHTTPClient) -> None:
        self.config = config
        self.http = http_client
        self.provider_config: ProviderConfig | None = config.get_provider(self.name)

    def is_configured(self) -> bool:
        """Comprueba si el provider está habilitado y correctamente configurado.

        Si no hay config.yaml (caso Cloud Functions), los providers que NO
        requieren API key se consideran activos por defecto.
        """
        if self.provider_config is not None:
            # Hay configuración explícita: respetar enabled/disabled
            if not self.provider_config.enabled:
                return False
            if self.requires_api_key:
                return bool(self.provider_config.get("api_key"))
            return True

        # Sin configuración explícita:
        # - Providers que NO necesitan API key → activos por defecto
        # - Providers que SÍ necesitan API key → desactivados
        return not self.requires_api_key

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Ejecuta una búsqueda y devuelve items encontrados.

        Args:
            criteria: Criterios de búsqueda definidos por el usuario.

        Returns:
            Lista de items encontrados.
        """
        ...

    async def get_detail(self, item_id: str) -> Item | None:
        """Obtiene detalles completos de un item específico.

        Implementación opcional — por defecto retorna None.
        """
        return None

    def _make_id(self, raw_id: str) -> str:
        """Crea un ID único con prefijo del provider: 'provider:raw_id'."""
        return f"{self.name}:{raw_id}"
