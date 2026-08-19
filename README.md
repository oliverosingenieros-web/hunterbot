# 🎯 HunterBot — Buscador Universal de Oportunidades

Agente autónomo en Python para rastrear, analizar precios y encontrar oportunidades/chollos en:
- **Inmobiliarias**: Idealista (API), Fotocasa, Pisos.com
- **Marketplaces**: Amazon, Wallapop
- **Náutica**: TopBarcos, CosasDeBarcos, Boat24
- **Web General**: DuckDuckGo Search

---

## 🚀 Instalación Rápida

1. Instala el proyecto en modo editable con pip:
```bash
pip install -e .
```

2. Copia la configuración base:
```bash
cp config.example.yaml config.yaml
```

---

## 💻 Ejemplos de Uso

### 1. Búsqueda de Inmuebles (Terrenos, Casas, Pisos)
```bash
hunterbot search --category real_estate --location "Malaga" --max-price 250000
```

### 2. Búsqueda de Barcos
```bash
hunterbot search --category boat --query "velero oceanico" --min-score 7.0
```

### 3. Búsqueda de Chollos en Amazon / Wallapop
```bash
hunterbot search --category product --query "iPad Pro M4" --min-score 6.5
```

### 4. Búsqueda Web Global
```bash
hunterbot search --provider web_search --query "ofertas viajes canarias chollo"
```

### 5. Ver Top Oportunidades Históricas
```bash
hunterbot opportunities --min-score 8.0
```

### 6. Exportar Datos a Excel/CSV
```bash
hunterbot export --output chollos_detectados.csv
```

---

## 📱 Configurar Alertas de Telegram por Proyecto

Para organizar las alertas por proyectos usando Topics en un supergrupo de Telegram:
1. Crea un bot con `@BotFather` y obtén el `bot_token`.
2. Añade el bot a un Supergrupo con Topics (Hilos) activados.
3. En `config.yaml`, mapea cada proyecto a su `message_thread_id`:
```yaml
notifications:
  telegram:
    enabled: true
    bot_token: "TU_BOT_TOKEN"
    group_chat_id: "-100XXXXXXXXXX"
    topics:
      "inmuebles_malaga": 102
      "barcos": 105
```
4. Lanza búsquedas asociadas al proyecto:
```bash
hunterbot search --location "Malaga" --project "inmuebles_malaga"
```
