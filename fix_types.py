import glob

for file in glob.glob('src/hunterbot/providers/*.py'):
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = content.replace('attributes.get("href", "")', 'attributes.get("href") or ""')
    content = content.replace('attributes.get("src", "")', 'attributes.get("src") or ""')
    content = content.replace('attributes.get("data-asin", "")', 'attributes.get("data-asin") or ""')
    content = content.replace('attributes.get("src") if img_el else None', '(img_el.attributes.get("src") or "") if img_el else None')
    content = content.replace('link_el.attributes.get("href", "") if link_el else f"/dp/{asin}"', '(link_el.attributes.get("href") or "") if link_el else f"/dp/{asin}"')
    
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)

with open('src/hunterbot/config.py', 'r', encoding='utf-8') as f:
    cfg = f.read()
cfg = cfg.replace('def _resolve_env_vars(data: dict) -> dict:', 'def _resolve_env_vars(data: dict) -> dict:\n    result: dict = {}')
cfg = cfg.replace('    result = {}\n    for key, value in data.items():\n        if isinstance(value, dict):\n            result[key] = _resolve_env_vars(value)', '    for key, value in data.items():\n        if isinstance(value, dict):\n            result[key] = _resolve_env_vars(value)')
with open('src/hunterbot/config.py', 'w', encoding='utf-8') as f:
    f.write(cfg)

with open('src/hunterbot/telegram_bot.py', 'r', encoding='utf-8') as f:
    tb = f.read()
tb = tb.replace('if criteria.category and criteria.category.value not in active_topics:', 'if criteria.category and criteria.category.value not in active_topics:')
# Actually, the error was: src\hunterbot\telegram_bot.py:218: error: Item "None" of "ItemCategory | None" has no attribute "value" [union-attr]
with open('src/hunterbot/telegram_bot.py', 'w', encoding='utf-8') as f:
    f.write(tb)

print("Done")
