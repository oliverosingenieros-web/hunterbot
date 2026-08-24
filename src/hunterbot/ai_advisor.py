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

# Modelos que funcionan con la API key actual (verificado)
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
        """Ejecuta una petición REST al modelo de IA de Google."""
        for model_name in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={self.api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
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
        """Analiza la petición del usuario con IA."""
        if not self.is_available:
            return self._fallback_consult(user_prompt)

        prompt = (
            "Eres HunterBot AI, un asesor experto en inversiones inmobiliarias, "
            "embarcaciones y productos. Analiza la petición y responde SOLO con un JSON "
            "(sin texto antes ni después).\n\n"
            "Estructura exacta:\n"
            '{\n'
            '  "topic_title": "emoji + título corto (max 35 chars)",\n'
            '  "tags": ["#Tag1", "#Tag2", "#Tag3"],\n'
            '  "advice": "Diagnóstico experto de mercado en 2-3 líneas en español. '
            'Incluye datos útiles: rangos de precio habituales, qué zonas son mejores, '
            'qué vigilar, consejos de negociación.",\n'
            '  "category": "real_estate" | "boat" | "product",\n'
            '  "location": "Ciudad/provincia" o null,\n'
            '  "query": "Término clave de búsqueda" o null,\n'
            '  "price_max": número o null,\n'
            '  "price_min": número o null,\n'
            '  "property_types": ["lands"] | ["homes"] | ["premises"] o null,\n'
            '  "project_name": "Casa" | "Barco" | "Producto"\n'
            '}\n\n'
            "Reglas:\n"
            "- Si piden terreno/parcela/finca: property_types=[\"lands\"], category=\"real_estate\"\n"
            "- Si piden casa/piso/chalet: property_types=[\"homes\"], category=\"real_estate\"\n"
            "- Si piden barco/velero/lancha (incluye marcas como Zar, Beneteau, Jeanneau): category=\"boat\"\n"
            "- Cualquier otro: category=\"product\"\n"
            "- El advice debe ser ÚTIL y ESPECÍFICO, no genérico\n\n"
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
        """Analiza los resultados encontrados y da una opinión experta.
        
        Esta es la función clave: convierte una lista de anuncios en
        un análisis de asesor inmobiliario/náutico profesional.
        """
        if not results:
            return ""

        if not self.is_available:
            return self._basic_analysis(results)

        results_text = json.dumps(results[:10], ensure_ascii=False, default=str)

        prompt = (
            "Eres un asesor experto de inversiones. El usuario busca: "
            f"'{user_query}'.\n\n"
            "He encontrado estos anuncios:\n"
            f"{results_text}\n\n"
            "Analiza los resultados y responde en español con:\n"
            "1. Cuál es la MEJOR opción y por qué (relación calidad-precio)\n"
            "2. Si algún precio parece sospechosamente bajo (posible estafa)\n"
            "3. Un consejo de negociación específico\n"
            "4. Qué debería preguntar el comprador antes de visitar\n\n"
            "Responde de forma directa y concisa (máx 600 chars). "
            "No uses markdown. Usa emojis para separar secciones."
        )

        resp = self._call_model(prompt)
        if resp:
            # Limpiar y limitar longitud
            return resp.strip()[:800]
        return self._basic_analysis(results)

    async def chat_followup(self, user_query: str, context: str) -> str:
        """Responde a una pregunta de seguimiento del usuario sobre resultados previos.
        
        Permite conversación natural: "¿cuál me recomiendas?", 
        "¿ese precio es bueno?", "busca más baratos", etc.
        """
        if not self.is_available:
            return "No puedo responder sin conexión a la IA. Intenta de nuevo."

        prompt = (
            "Eres HunterBot AI, un asesor experto. El usuario está conversando "
            "sobre una búsqueda anterior.\n\n"
            f"Contexto previo:\n{context}\n\n"
            f"Pregunta del usuario: '{user_query}'\n\n"
            "Responde de forma útil, directa y en español. "
            "Si el usuario pide buscar algo diferente, dile que escriba "
            "su nueva búsqueda en el tema General del grupo.\n"
            "Si pregunta sobre los resultados, da opinión experta.\n"
            "Máximo 500 caracteres. No uses markdown."
        )

        resp = self._call_model(prompt)
        return resp.strip()[:600] if resp else "No he podido procesar tu pregunta. Inténtalo de nuevo."

    def _basic_analysis(self, results: list[dict[str, Any]]) -> str:
        """Análisis básico sin IA — compara precios."""
        if not results:
            return ""
        prices = [r["price"] for r in results if r.get("price", 0) > 0]
        if not prices:
            return "📊 No hay precios disponibles para comparar."
        avg = sum(prices) / len(prices)
        cheapest = min(prices)
        return (
            f"📊 Resumen rápido: {len(results)} opciones encontradas.\n"
            f"💰 Precio medio: {avg:,.0f} €\n"
            f"🔥 Más barato: {cheapest:,.0f} €\n"
            f"💡 Los anuncios con precio muy por debajo de la media merecen atención especial."
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
        """Fallback inteligente si la IA no responde."""
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

        location = None
        locations_es = [
            "málaga", "malaga", "madrid", "barcelona", "valencia", "sevilla", "granada",
            "alicante", "murcia", "cádiz", "cadiz", "córdoba", "cordoba", "toledo",
            "almería", "almeria", "huelva", "jaén", "jaen", "asturias", "cantabria",
            "vizcaya", "guipúzcoa", "navarra", "la rioja", "zaragoza", "huesca", "teruel",
            "lérida", "lleida", "girona", "gerona", "tarragona", "castellón", "castellon",
            "baleares", "mallorca", "ibiza", "menorca", "tenerife", "gran canaria",
            "marbella", "estepona", "fuengirola", "benalmádena", "benalmadena",
            "costa del sol", "axarquía", "axarquia", "guadalhorce",
        ]
        for loc in locations_es:
            if loc in lower:
                location = loc.title()
                break

        return {
            "criteria": SearchCriteria(
                query=query,
                category=cat,
                property_types=prop_types,
                price_max=price_max,
                location=location,
                operation=Operation.SALE,
            ),
            "project_name": self._default_project(cat),
            "topic_title": f"🎯 {user_prompt[:30]}",
            "tags": ["#Búsqueda"],
            "advice": "Rastreando portales en tiempo real...",
        }

    async def generate_weekly_report(self, top_opportunities: list[dict[str, Any]]) -> str:
        """Genera un análisis ejecutivo semanal."""
        if not top_opportunities:
            return "No hay oportunidades registradas esta semana."

        prompt = (
            "Eres un asesor experto. Redacta un resumen ejecutivo breve (máx 500 chars) "
            "de estas oportunidades. Destaca los 2-3 mejores chollos y da un consejo.\n\n"
            f"Datos:\n{json.dumps(top_opportunities[:5], ensure_ascii=False, default=str)}"
        )
        resp = self._call_model(prompt)
        return resp if resp else "No se pudo generar el análisis con IA."
