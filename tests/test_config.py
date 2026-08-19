"""Tests para la carga de configuración."""

from pathlib import Path
from hunterbot.config import HunterConfig, load_config


def test_load_default_config():
    cfg = load_config(None)
    assert isinstance(cfg, HunterConfig)
    assert cfg.is_provider_enabled("fotocasa") is True
    assert cfg.is_provider_enabled("amazon") is True
    assert cfg.is_provider_enabled("topbarcos") is True
    assert cfg.opportunity_threshold >= 5.0
