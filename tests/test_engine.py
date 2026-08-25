"""Tests para HunterEngine y alertas de salud."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hunterbot.config import HunterConfig, TelegramConfig
from hunterbot.engine import HunterEngine
from hunterbot.models import SearchCriteria, ItemCategory

@pytest.fixture
def mock_config():
    cfg = HunterConfig(database_path=":memory:")
    cfg.telegram = TelegramConfig(enabled=True, bot_token="fake", admin_chat_id="123")
    return cfg

@pytest.mark.asyncio
async def test_engine_health_alert(mock_config):
    """Prueba que el engine llama a la alerta de salud si el provider falla 3 veces."""
    engine = HunterEngine(mock_config)
    
    # Mockear un provider que devuelve lista vacía
    mock_provider = MagicMock()
    mock_provider.name = "fake_provider"
    mock_provider.category = ItemCategory.OTHER
    mock_provider.search = AsyncMock(return_value=[])
    
    engine.providers = [mock_provider]
    
    criteria = SearchCriteria(query="test", provider="fake_provider")
    
    with patch("hunterbot.database_firebase.FirestoreDatabase") as MockDB, \
         patch("hunterbot.notifications.TelegramNotifier") as MockNotifier:
        
        # Simular Firestore habilitado y devolviendo 3 fallos
        mock_db_instance = MockDB.return_value
        mock_db_instance.enabled = True
        mock_db_instance.track_provider_health.return_value = 3
        
        mock_notifier_instance = MockNotifier.return_value
        mock_notifier_instance.notify_health_alert = AsyncMock(return_value=True)
        
        # Ejecutar búsqueda
        await engine.search_all(criteria)
        
        # Verificar que se trackeó el fallo
        mock_db_instance.track_provider_health.assert_called_with("fake_provider", success=False)
        
        # Verificar que se envió la alerta
        mock_notifier_instance.notify_health_alert.assert_called_once_with(
            "fake_provider", "0 items devueltos (posible bloqueo o cambio CSS)"
        )
