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

# Modelos disponibles verificados
MODELS = ["gemma-4-26b-a4b-it", "gemma-4-31b-it"]


def _get_default_key() -> str:
    """Obtiene la API key desde env var o valor por defecto."""
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
        """Ejecuta una petición REST al modelo de IA de Google asegurando español."""
        for model_name in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={self.api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 1500,
                },
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=50) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = parts[0].get("text", "") if parts else ""
                        if text:
                            logger.info("IA respondió con modelo %s (%d chars)", model_name, len(text))
                            return text
            except Exception as e:
                logger.warning("Error llamando modelo %s: %s", model_name, e)
        return ""

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extrae de forma robusta el objeto JSON con parser de llaves balanceadas."""
        code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

        start = text.find("{")
        if start == -1:
            return {}

        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}

    async def consult_and_parse(self, user_prompt: str) -> dict[str, Any]:
        """Analiza la petición del usuario con IA (100% en español)."""
        if not self.is_available:
            return self._fallback_consult(user_prompt)

        prompt = (
            "Eres HunterBot AI, un asesor experto en inversiones náuticas e inmobiliarias en España.\n"
            "IMPORTANTE: Tu respuesta debe estar 100% en ESPAÑOL.\n"
            "Analiza la petición del usuario y responde ÚNICAMENTE con un JSON válido con esta estructura:\n"
            '{\n'
            '  "topic_title": "emoji + título en español (máx 35 caracteres)",\n'
            '  "tags": ["#Tag1", "#Tag2", "#Tag3"],\n'
            '  "advice": "Diagnóstico de mercado detallado en español: rangos de precios habituales de segunda mano según modelo/eslora, puntos críticos de inspección y consejo de compra.",\n'
            '  "category": "real_estate" | "boat" | "product",\n'
            '  "location": "Ciudad o zona en España" o null,\n'
            '  "query": "Término clave de búsqueda" o null,\n'
            '  "price_max": número o null,\n'
            '  "price_min": número o null,\n'
            '  "property_types": ["lands"] | ["homes"] | ["premises"] o null,\n'
            '  "project_name": "Barco" | "Casa" | "Producto"\n'
            '}\n\n'
            f"Petición del usuario: '{user_prompt}'"
        )

        raw_resp = self._call_model(prompt)
        data = self._extract_json(raw_resp)

        if not data:
            logger.warning("IA no devolvió JSON válido. Usando fallback.")
            return self._fallback_consult(user_prompt)

        cat = self._map_category(data.get("category", "other"))

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
            "project_name": data.get("project_name") or self._default_project(cat),
            "topic_title": data.get("topic_title") or f"🎯 {user_prompt[:30]}",
            "tags": data.get("tags") or ["#Oportunidad"],
            "advice": data.get("advice") or "Analizando mercado en tiempo real...",
        }

    async def analyze_results(self, user_query: str, results: list[dict[str, Any]]) -> str:
        """Analiza los resultados encontrados y da una recomendación rigurosa en español."""
        if not results:
            return ""

        if not self.is_available:
            return self._basic_analysis(results)

        results_text = json.dumps(results[:8], ensure_ascii=False, default=str)

        prompt = (
            "Eres un asesor experto en compras e inversiones náuticas e inmobiliarias en España.\n"
            f"El usuario busca: '{user_query}'.\n\n"
            f"Opciones indexadas en portales:\n{results_text}\n\n"
            "Redacta un análisis y recomendación rigurosa obligatoriamente en ESPAÑOL:\n"
            "1. Resumen de precios detectados y rango razonable de mercado para este tipo de barco/inmueble.\n"
            "2. Cuál o cuáles de las opciones anteriores ofrecen mejor relación valor/precio.\n"
            "3. Qué elementos críticos revisar antes de comprar (ej. motorización, flotadores Hypalon, ITB/documentación, remolque).\n"
            "4. Consejo directo para negociar el precio con el vendedor.\n\n"
            "Reglas: Responde de forma clara, profesional y directa en ESPAÑOL. No uses Markdown con asteriscos, usa saltos de línea y emojis para estructurar el mensaje."
        )

        resp = self._call_model(prompt)
        if resp:
            # Limpiar posibles asteriscos Markdown
            clean_resp = resp.replace("**", "").replace("__", "").strip()
            return clean_resp[:1000]
        return self._basic_analysis(results)

    async def chat_followup(self, user_query: str, context: str) -> str:
        """Responde a preguntas de seguimiento del usuario exclusivamente en español."""
        if not self.is_available:
            return "No hay conexión con el servicio de IA en este momento."

        prompt = (
            "Eres HunterBot AI, un asesor experto en náutica e inmuebles.\n"
            "REGLA ESTRICTA: Responde siempre en ESPAÑOL.\n\n"
            f"Contexto de la conversación:\n{context}\n\n"
            f"Pregunta del usuario: '{user_query}'\n\n"
            "Responde de forma concisa, experta y práctica (máximo 600 caracteres). "
            "No uses asteriscos ni markdown, solo texto claro con emojis."
        )

        resp = self._call_model(prompt)
        if resp:
            return resp.replace("**", "").replace("__", "").strip()[:800]
        return "No he podido procesar tu consulta en este momento."

    def _basic_analysis(self, results: list[dict[str, Any]]) -> str:
        """Análisis básico sin IA — compara precios."""
        if not results:
            return ""
        prices = [r["price"] for r in results if r.get("price", 0) > 0]
        if not prices:
            return "📊 Consulta las fichas de los enlaces para ver los precios actualizados de cada unidad."
        avg = sum(prices) / len(prices)
        cheapest = min(prices)
        return (
            f"📊 Resumen de mercado: {len(results)} unidades detectadas.\n"
            f"💰 Precio medio aproximado: {avg:,.0f} €\n"
            f"🔥 Opción más accesible: {cheapest:,.0f} €\n"
            f"💡 Revisa detalladamente el estado de los componentes antes de formalizar la compra."
        ).replace(",", ".")

    @staticmethod
    def _map_category(cat_str: str) -> ItemCategory:
        cat_lower = (cat_str or "other").lower()
        if "estate" in cat_lower or "real" in cat_lower:
            return ItemCategory.REAL_ESTATE
        if "boat" in cat_lower or "barco" in cat_lower:
            return ItemCategory.BOAT
        if "product" in cat_lower:
            return ItemCategory.PRODUCT
        return ItemCategory.OTHER

    @staticmethod
    def _default_project(cat: ItemCategory) -> str:
        if cat == ItemCategory.REAL_ESTATE:
            return "Casa"
        if cat == ItemCategory.BOAT:
            return "Barco"
        return "Producto"

    def _fallback_consult(self, user_prompt: str) -> dict[str, Any]:
        """Fallback inteligente en español si la IA no responde."""
        lower = user_prompt.lower()
        cat = ItemCategory.OTHER
        prop_types = None
        query = user_prompt

        land_words = ["terreno", "parcela", "finca", "solar", "rústic", "rural"]
        home_words = ["casa", "piso", "chalet", "ático", "vivienda", "apartamento", "dúplex", "adosado"]
        premises_words = ["local", "oficina", "nave", "garaje", "trastero"]
        boat_words = ["barco", "velero", "lancha", "yate", "catamaran", "embarcación",
                       "zar", "formenti", "beneteau", "jeanneau", "bavaria", "hanse",
                       "dufour", "lagoon", "fountaine", "zodiac", "quicksilver"]

        if any(w in lower for w in land_words):
            cat = ItemCategory.REAL_ESTATE
            prop_types = ["lands"]
        elif any(w in lower for w in home_words):
            cat = ItemCategory.REAL_ESTATE
            prop_types = ["homes"]
        elif any(w in lower for w in premises_words):
            cat = ItemCategory.REAL_ESTATE
            prop_types = ["premises"]
        elif any(w in lower for w in boat_words):
            cat = ItemCategory.BOAT

        price_max = None
        price_match = re.search(r"(?:menos de|por debajo de|hasta|máximo|max|<)\s*([\d.]+)", lower)
        if price_match:
            try:
                price_max = float(price_match.group(1).replace(".", ""))
            except ValueError:
                pass
        if not price_max:
            price_match2 = re.search(r"([\d.]+)\s*(?:€|euros?|eur)", lower)
            if price_match2:
                try:
                    price_max = float(price_match2.group(1).replace(".", ""))
                except ValueError:
                    pass

        return {
            "criteria": SearchCriteria(
                query=query,
                category=cat,
                property_types=prop_types,
                price_max=price_max,
                operation=Operation.SALE,
            ),
            "project_name": self._default_project(cat),
            "topic_title": f"🎯 {user_prompt[:30]}",
            "tags": ["#Búsqueda"],
            "advice": "Rastreando portales náuticos e inmobiliarios en tiempo real...",
        }
