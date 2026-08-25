"""Provider para la API oficial de Idealista (OAuth2)."""

from __future__ import annotations

import base64
import logging
from typing import Any

from hunterbot.models import Item, ItemCategory, Operation, SearchCriteria
from hunterbot.providers import register
from hunterbot.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Mapeo básico de provincias a location_id común si se necesita
PROVINCE_LOCATION_MAP: dict[str, str] = {
    "madrid": "0-EU-ES-28",
    "barcelona": "0-EU-ES-08",
    "valencia": "0-EU-ES-46",
    "malaga": "0-EU-ES-29",
    "alicante": "0-EU-ES-03",
    "sevilla": "0-EU-ES-41",
    "baleares": "0-EU-ES-07",
    "palma": "0-EU-ES-07",
}


@register
class IdealistaProvider(BaseProvider):
    """Provider oficial de Idealista vía API REST OAuth2."""

    name = "idealista"
    display_name = "Idealista (API)"
    category = ItemCategory.REAL_ESTATE
    requires_api_key = True
    default_rate_limit = 2.0
    base_url = "https://api.idealista.com"

    def __init__(self, config: Any, http_client: Any) -> None:
        super().__init__(config, http_client)
        self._token: str | None = None

    async def _get_access_token(self) -> str:
        """Obtiene un token OAuth2 utilizando api_key y api_secret."""
        if self._token:
            return self._token

        if not self.provider_config:
            raise ValueError("Configuración de Idealista no encontrada")

        api_key = self.provider_config.get("api_key")
        api_secret = self.provider_config.get("api_secret")

        if not api_key or not api_secret:
            raise ValueError("Faltan api_key o api_secret para Idealista")

        credentials = f"{api_key}:{api_secret}"
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "utf-8"
        )

        url = f"{self.base_url}/oauth/token"
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        response = await self.http.post(
            url, data=data, headers=headers, rate_limit=self.default_rate_limit
        )
        response.raise_for_status()
        json_data = response.json()
        self._token = json_data.get("access_token")
        if not self._token:
            raise ValueError("No se pudo obtener el access_token de Idealista")
        return self._token

    async def search(self, criteria: SearchCriteria) -> list[Item]:
        """Ejecuta búsqueda en la API de Idealista."""
        try:
            token = await self._get_access_token()
        except Exception as e:
            logger.error("Error al autenticar con Idealista: %s", e)
            return []

        url = f"{self.base_url}/3.5/es/search"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        location_id = criteria.location_id
        if not location_id and criteria.location:
            loc_key = criteria.location.lower().strip()
            location_id = PROVINCE_LOCATION_MAP.get(loc_key, "0-EU-ES-28")

        params: dict[str, Any] = {
            "country": "es",
            "operation": "sale" if criteria.operation == Operation.SALE else "rent",
            "propertyType": criteria.property_types[0] if criteria.property_types else "homes",
            "maxItems": 50,
        }

        if criteria.latitude and criteria.longitude:
            params["center"] = f"{criteria.latitude},{criteria.longitude}"
            params["distance"] = 15000  # Default 15km
        elif location_id:
            params["locationId"] = location_id

        if criteria.price_min is not None:
            params["minPrice"] = int(criteria.price_min)
        if criteria.price_max is not None:
            params["maxPrice"] = int(criteria.price_max)
        if criteria.size_min_m2 is not None:
            params["minSize"] = int(criteria.size_min_m2)
        if criteria.size_max_m2 is not None:
            params["maxSize"] = int(criteria.size_max_m2)
        if criteria.rooms_min is not None:
            params["minRooms"] = int(criteria.rooms_min)

        items: list[Item] = []
        try:
            resp = await self.http.post(
                url, headers=headers, data=params, rate_limit=self.default_rate_limit
            )
            
            try:
                from hunterbot.database_firebase import FirestoreDatabase
                fb_db = FirestoreDatabase()
                usage, days_rem = fb_db.track_idealista_usage()
                self._quota_usage = usage
                self._quota_days = days_rem
            except Exception as e:
                logger.error("Error al contar cuota idealista: %s", e)
                
            resp.raise_for_status()
            data = resp.json()
            element_list = data.get("elementList", [])

            for el in element_list:
                item_id = self._make_id(str(el.get("propertyCode", "")))
                price = float(el.get("price", 0))
                size = float(el.get("size", 0)) if el.get("size") else None
                item = Item(
                    id=item_id,
                    provider=self.name,
                    category=ItemCategory.REAL_ESTATE,
                    title=el.get("suggestedTexts", {}).get("title")
                    or el.get("propertyType", "Inmueble"),
                    price=price,
                    url=el.get("url")
                    or f"https://www.idealista.com/inmueble/{el.get('propertyCode')}/",
                    location=f"{el.get('municipality', '')}, {el.get('district', '')}".strip(
                        ", "
                    ),
                    latitude=el.get("latitude"),
                    longitude=el.get("longitude"),
                    size_m2=size,
                    rooms=el.get("rooms"),
                    bathrooms=el.get("bathrooms"),
                    property_type=el.get("propertyType"),
                    description=el.get("description"),
                    image_url=el.get("thumbnail"),
                    extra={"floor": el.get("floor"), "hasLift": el.get("hasLift")},
                )
                items.append(item)
        except Exception as e:
            logger.error("Error buscando en Idealista: %s", e)

        return items
