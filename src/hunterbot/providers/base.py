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

    def css_first_from_config(self, node: Any, field_key: str) -> Any:
        """
        Busca un elemento HTML en 'node' usando los selectores CSS definidos en
        selectors.yaml para este provider y este campo.
        Devuelve el primer elemento HTML encontrado o None.
        """
        # Obtenemos los selectores para este provider
        provider_selectors = self.config.selectors.get(self.name, {})
        # Obtenemos la lista de selectores para el campo (ej: 'title')
        field_selectors = provider_selectors.get(field_key)
        
        if not field_selectors:
            return None
            
        if isinstance(field_selectors, str):
            field_selectors = [field_selectors]
            
        # Probamos cada selector en orden
        for selector in field_selectors:
            el = node.css_first(selector)
            if el:
                return el
                
        return None

    def css_from_config(self, node: Any, field_key: str) -> list[Any]:
        """
        Igual que css_first_from_config pero devuelve todos los elementos.
        Si encuentra coincidencias con el primer selector válido, las devuelve.
        """
        provider_selectors = self.config.selectors.get(self.name, {})
        field_selectors = provider_selectors.get(field_key)
        
        if not field_selectors:
            return []
            
        if isinstance(field_selectors, str):
            field_selectors = [field_selectors]
            
        for selector in field_selectors:
            els = node.css(selector)
            if els:
                return els
                
        return []
