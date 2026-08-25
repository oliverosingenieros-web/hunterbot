import sys

with open('src/hunterbot/config.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_load_config = False

for line in lines:
    if line.startswith('def load_config'):
        in_load_config = True
        break
    new_lines.append(line)

new_lines.append('''def load_config(path: Path | str | None = None) -> HunterConfig:
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

    selectors = {}
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
''')

with open('src/hunterbot/config.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
