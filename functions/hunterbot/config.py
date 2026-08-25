"""Carga y validación de configuración YAML para HunterBot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

import logging
logger = logging.getLogger(__name__)


DEFAULT_CONFIG_PATHS = [
    Path("config.yaml"),
    Path("config.yml"),
    Path.home() / ".hunterbot" / "config.yaml",
]

_DEFAULTS: dict[str, Any] = {
    "providers": {
        "idealista": {"enabled": False, "api_key": "", "api_secret": ""},
        "fotocasa": {"enabled": True},
        "pisos_com": {"enabled": True},
        "amazon": {"enabled": True, "domain": "amazon.es"},
        "wallapop": {"enabled": True},
        "web_search": {"enabled": True},
        "topbarcos": {"enabled": True},
        "cosasdebarcos": {"enabled": True},
        "boat24": {"enabled": True},
    },
    "real_estate": {"zones": [], "filters": {}},
    "products": {"searches": []},
    "boats": {"searches": [], "zones": []},
    "web_searches": [],
    "scoring": {
        "real_estate": {
            "price_vs_zone_avg": 0.35,
            "price_per_m2": 0.25,
            "days_on_market": 0.15,
            "price_reduction": 0.15,
            "listing_quality": 0.10,
        },
        "products": {
            "discount_percent": 0.40,
            "price_vs_category_avg": 0.25,
            "product_rating": 0.15,
            "seller_rating": 0.10,
            "historical_low": 0.10,
        },
        "boats": {
            "price_vs_avg": 0.30,
            "price_per_meter": 0.25,
            "age_value": 0.20,
            "engine_hours": 0.15,
            "listing_quality": 0.10,
        },
        "opportunity_threshold": 6.5,
    },
    "notifications": {
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "group_chat_id": "",
            "topics": {},
            "min_score": 7.5,
        },
        "terminal": {"show_all": False, "max_results": 20},
    },
    "general": {
        "database_path": "~/.hunterbot/hunterbot.db",
        "cache_ttl_hours": 6,
        "max_pages_per_provider": 3,
        "respect_robots_txt": True,
        "log_level": "INFO",
    },
}


@dataclass
class TelegramConfig:
    """Configuración de notificaciones Telegram."""

    enabled: bool = False
    bot_token: str = ""
    group_chat_id: str = ""
    admin_chat_id: str = ""
    topics: dict[str, int] = field(default_factory=dict)
    min_score: float = 7.5


@dataclass
class ProviderConfig:
    """Configuración de un provider individual."""

    name: str
    enabled: bool = True
    settings: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


@dataclass
class ScoringWeights:
    """Pesos de scoring para una categoría."""

    weights: dict[str, float] = field(default_factory=dict)

    def get(self, factor: str) -> float:
        return self.weights.get(factor, 0.0)


@dataclass
class HunterConfig:
    """Configuración completa de HunterBot."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    real_estate: dict[str, Any] = field(default_factory=dict)
    products: dict[str, Any] = field(default_factory=dict)
    boats: dict[str, Any] = field(default_factory=dict)
    web_searches: list[dict[str, Any]] = field(default_factory=list)
    scoring: dict[str, ScoringWeights] = field(default_factory=dict)
    opportunity_threshold: float = 6.5
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    terminal_show_all: bool = False
    terminal_max_results: int = 20
    database_path: Path = field(
        default_factory=lambda: Path.home() / ".hunterbot" / "hunterbot.db"
    )
    cache_ttl_hours: int = 6
    max_pages_per_provider: int = 3
    respect_robots_txt: bool = True
    log_level: str = "INFO"
    selectors: dict[str, Any] = field(default_factory=dict)
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def is_provider_enabled(self, name: str) -> bool:
        provider = self.providers.get(name)
        return provider.enabled if provider else False

    def get_provider(self, name: str) -> ProviderConfig | None:
        return self.providers.get(name)

    def get_scoring_weights(self, category: str) -> ScoringWeights:
        return self.scoring.get(category, ScoringWeights())

    def get_zones(self, category: str = "real_estate") -> list[dict[str, Any]]:
        section = self._raw.get(category, {})
        return section.get("zones", [])

    def get_searches(self, category: str = "products") -> list[dict[str, Any]]:
        section = self._raw.get(category, {})
        return section.get("searches", [])


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge profundo de dos diccionarios."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_env_vars(data: dict) -> dict:
    result: dict = {}
    """Resuelve variables de entorno en valores string."""
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = _resolve_env_vars(value)
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            result[key] = os.environ.get(env_var, "")
        else:
            result[key] = value
    return result


def _parse_providers(raw: dict) -> dict[str, ProviderConfig]:
    """Parsea la sección de providers."""
    providers_raw = raw.get("providers", {})
    providers = {}
    for name, cfg in providers_raw.items():
        if isinstance(cfg, dict):
            enabled = cfg.pop("enabled", True)
            providers[name] = ProviderConfig(name=name, enabled=enabled, settings=cfg)
        else:
            providers[name] = ProviderConfig(name=name, enabled=bool(cfg))
    return providers


def _parse_scoring(raw: dict) -> tuple[dict[str, ScoringWeights], float]:
    """Parsea la sección de scoring."""
    scoring_raw = raw.get("scoring", {})
    threshold = scoring_raw.pop("opportunity_threshold", 6.5)
    weights = {}
    for category, w in scoring_raw.items():
        if isinstance(w, dict):
            weights[category] = ScoringWeights(weights=w)
    return weights, threshold


def _parse_telegram(raw: dict) -> TelegramConfig:
    """Parsea la sección de Telegram."""
    notif = raw.get("notifications", {})
    tg = notif.get("telegram", {})

    # Override con env vars
    bot_token = tg.get("bot_token", "") or os.environ.get(
        "HUNTERBOT_TELEGRAM_BOT_TOKEN", ""
    )
    group_chat_id = tg.get("group_chat_id", "") or os.environ.get(
        "HUNTERBOT_TELEGRAM_CHAT_ID", ""
    )
    admin_chat_id = tg.get("admin_chat_id", "") or os.environ.get(
        "HUNTERBOT_TELEGRAM_ADMIN_CHAT_ID", ""
    )

    return TelegramConfig(
        enabled=tg.get("enabled", False),
        bot_token=bot_token,
        group_chat_id=group_chat_id,
        admin_chat_id=admin_chat_id,
        topics=tg.get("topics", {}),
        min_score=tg.get("min_score", 7.5),
    )


def load_config(path: Path | str | None = None) -> HunterConfig:
    """Carga la configuración desde un archivo YAML."""
    config_path: Path | None = None

    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            config_path = None
    else:
        for candidate in DEFAULT_CONFIG_PATHS:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is not None and yaml is not None:
        with open(config_path, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    else:
        user_config = {}

    raw = _deep_merge(_DEFAULTS, user_config)
    raw = _resolve_env_vars(raw)

    providers_raw = raw.get("providers", {})
    idealista_cfg = providers_raw.get("idealista", {})
    if not idealista_cfg.get("api_key"):
        idealista_cfg["api_key"] = os.environ.get("HUNTERBOT_IDEALISTA_API_KEY", "")
    if not idealista_cfg.get("api_secret"):
        idealista_cfg["api_secret"] = os.environ.get("HUNTERBOT_IDEALISTA_API_SECRET", "")
    if idealista_cfg.get("api_key") and idealista_cfg.get("api_secret"):
        idealista_cfg["enabled"] = True

    providers = _parse_providers(raw)
    scoring, threshold = _parse_scoring(raw)
    telegram = _parse_telegram(raw)

    selectors: dict[str, Any] = {}
    if config_path:
        selectors_path = config_path.parent / "selectors.yaml"
        if selectors_path.exists():
            try:
                with open(selectors_path, "r", encoding="utf-8") as f:
                    selectors = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning("No se pudo cargar selectors.yaml: %s", e)

    general = raw.get("general", {})
    db_path_str = general.get("database_path", "~/.hunterbot/hunterbot.db")
    db_path = Path(db_path_str).expanduser()

    terminal_cfg = raw.get("notifications", {}).get("terminal", {})

    return HunterConfig(
        providers=providers,
        real_estate=raw.get("real_estate", {}),
        products=raw.get("products", {}),
        boats=raw.get("boats", {}),
        web_searches=raw.get("web_searches", []),
        scoring=scoring,
        opportunity_threshold=threshold,
        telegram=telegram,
        terminal_show_all=terminal_cfg.get("show_all", False),
        terminal_max_results=terminal_cfg.get("max_results", 20),
        database_path=db_path,
        cache_ttl_hours=general.get("cache_ttl_hours", 6),
        max_pages_per_provider=general.get("max_pages_per_provider", 3),
        respect_robots_txt=general.get("respect_robots_txt", True),
        log_level=general.get("log_level", "INFO"),
        selectors=selectors,
        _raw=raw,
    )
