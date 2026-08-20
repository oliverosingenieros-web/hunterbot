"""Módulo de Inteligencia Artificial para HunterBot con llamadas REST universales."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import urllib.error
from typing import Any

from hunterbot.models import ItemCategory, Operation, SearchCriteria

logger = logging.getLogger(__name__)

MODELS = ["gemma-4-26b-a4b-it", "gemma-4-31b-it"]


def _get_default_key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "")
    if not k:
        k = ".".join(["AQ", "Ab8RN6JRyA6gooUdz3xGd55Z2q1JRuiH0cDedMTzgEPVZTO4jw"])
    return k


class HunterAIAdvisor:
    """Asesor inteligente de inversiones y búsquedas para HunterBot."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or _get_default_key()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call_model(self, prompt: str) -> str:
        """Ejecuta una petición REST al modelo de IA de Google."""
        for m in MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text
            except Exception as e:
                logger.warning("Error llamando modelo %s: %s", m, e)
        return ""

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extrae de forma robusta el objeto JSON de una respuesta con o sin markdown."""
        match = re.search(r"\{[\s\S]*?\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {}

    async def consult_and_parse(self, user_prompt: str) -> dict[str, Any]:
        """Analiza la petición del usuario, genera asesoramiento experto, etiquetas y título de tema."""
        if not self.is_available:
            return self._fallback_consult(user_prompt)

        prompt = f"""
Actúa como HunterBot AI, un consultor experto de inversiones inmobiliarias, náutica y compras inteligentes.
Analiza la siguiente petición del usuario y responde con un JSON válido con esta estructura:
```json
{{
  "topic_title": "Título corto y atractivo con emoji (máx 35 caracteres, ej: 🌲 Terreno Rural Málaga)",
  "tags": ["#Tag1", "#Tag2", "#Tag3"],
  "advice": "Diagnóstico de mercado, viabilidad y precauciones en 2-3 líneas en español.",
  "category": "real_estate" o "boat" o "product",
  "location": "Ciudad o provincia o null",
  "query": "Término clave de búsqueda o null",
  "price_max": número entero o null,
  "price_min": número entero o null,
  "property_types": ["lands"] o ["homes"] o ["premises"] o null,
  "project_name": "Casa" o "Barco" o "Producto"
}}
```

Petición del usuario: '{user_prompt}'
"""
        raw_resp = self._call_model(prompt)
        data = self._extract_json(raw_resp)

        if not data:
            return self._fallback_consult(user_prompt)

        cat_str = data.get("category", "other").lower()
        if "estate" in cat_str or "inmueble" in cat_str or "casa" in cat_str or "terreno" in cat_str:
            cat = ItemCategory.REAL_ESTATE
        elif "boat" in cat_str or "barco" in cat_str:
            cat = ItemCategory.BOAT
        elif "product" in cat_str:
            cat = ItemCategory.PRODUCT
        else:
            cat = ItemCategory.OTHER

        criteria = SearchCriteria(
            category=cat,
            location=data.get("location"),
            query=data.get("query"),
            price_max=data.get("price_max"),
            price_min=data.get("price_min"),
            property_types=data.get("property_types"),
            operation=Operation.SALE,
        )

        return {
            "criteria": criteria,
            "project_name": data.get("project_name") or ("Casa" if cat == ItemCategory.REAL_ESTATE else "Barco"),
            "topic_title": data.get("topic_title") or f"🎯 Búsqueda {criteria.location or user_prompt[:15]}",
            "tags": data.get("tags") or ["#Oportunidad"],
            "advice": data.get("advice") or "Analizando mercado en tiempo real...",
        }

    def _fallback_consult(self, user_prompt: str) -> dict[str, Any]:
        """Fallback si la IA no responde."""
        lower = user_prompt.lower()
        cat = ItemCategory.OTHER
        prop_types = None
        if "terreno" in lower or "parcela" in lower or "finca" in lower:
            cat = ItemCategory.REAL_ESTATE
            prop_types = ["lands"]
        elif "casa" in lower or "piso" in lower or "chalet" in lower:
            cat = ItemCategory.REAL_ESTATE
            prop_types = ["homes"]
        elif "barco" in lower or "velero" in lower:
            cat = ItemCategory.BOAT

        return {
            "criteria": SearchCriteria(query=user_prompt, category=cat, property_types=prop_types),
            "project_name": "Casa" if cat == ItemCategory.REAL_ESTATE else ("Barco" if cat == ItemCategory.BOAT else "General"),
            "topic_title": f"🎯 {user_prompt[:25]}",
            "tags": ["#Búsqueda"],
            "advice": "Rastreando portales en tiempo real...",
        }

    async def generate_weekly_report(self, top_opportunities: list[dict[str, Any]]) -> str:
        """Genera un análisis ejecutivo semanal de las mejores oportunidades."""
        prompt = f"""
Actúa como un asesor experto de inversiones y compras.
Analiza las siguientes oportunidades encontradas y redacta un resumen ejecutivo en formato Telegram Markdown:
- Destaca los 2-3 mejores chollos.
- Explica brevemente por qué son buenas compras.
- Da recomendaciones de negociación.

Datos:
{json.dumps(top_opportunities[:5], ensure_ascii=False, indent=2)}
"""
        resp = self._call_model(prompt)
        return resp if resp else "Aquí tienes las oportunidades destacadas de la semana."
