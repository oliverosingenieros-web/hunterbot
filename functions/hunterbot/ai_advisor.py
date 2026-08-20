"""Módulo de Inteligencia Artificial (Gemini) para HunterBot.

Permite:
1. Interpretar peticiones en lenguaje natural (ej. "búscame casas cerca de la playa por menos de 200k").
2. Analizar descripciones y fotos de los anuncios para detectar pros, contras y potencial de inversión.
3. Generar resúmenes ejecutivos semanales de las mejores oportunidades.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from hunterbot.models import ItemCategory, Operation, SearchCriteria

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


class HunterAIAdvisor:
    """Asesor inteligente para HunterBot."""

    def __init__(self, api_key: str | None = None) -> None:
        if not api_key:
            try:
                from hunterbot.config import load_config
                cfg = load_config()
                api_key = cfg._raw.get("gemini", {}).get("api_key")
            except Exception:
                pass
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.client = None
        if HAS_GENAI and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info("🧠 Gemini AI Advisor conectado exitosamente.")
            except Exception as e:
                logger.error("Error iniciando Gemini Client: %s", e)

    @property
    def is_available(self) -> bool:
        return bool(self.client is not None)

    async def consult_and_parse(self, user_prompt: str) -> dict[str, Any]:
        """Analiza la petición del usuario, genera asesoramiento experto, etiquetas y título de tema."""
        if not self.is_available:
            return {
                "criteria": SearchCriteria(query=user_prompt),
                "project_name": "General",
                "topic_title": f"🔍 {user_prompt[:25]}",
                "tags": ["#Búsqueda"],
                "advice": "Búsqueda estándar iniciada.",
            }

        system_instruction = """
        Eres HunterBot AI, un consultor experto de inversiones inmobiliarias, náutica y compras inteligentes.
        Tu misión es analizar la petición del usuario y devolver un JSON con:
        1. 'topic_title': Título corto, visual y atractivo para un tema de Telegram (máx 35 caracteres), incluyendo un emoji adecuado (ej. '🏡 Casa Málaga <200k', '🌲 Finca Rústica Segovia', '⛵ Velero 10m <40k', '💻 MacBook M3 Ofertas').
        2. 'tags': Lista de 3-5 hashtags relevantes (ej. ['#Inmuebles', '#Terreno', '#Málaga', '#Inversión']).
        3. 'advice': Asesoramiento y análisis breve (2-3 líneas) explicando:
           - Viabilidad del presupuesto según el mercado actual.
           - Puntos clave y precauciones a revisar (ej. escrituras, agua/luz en rústico, ITB en barcos, estado técnico).
        4. 'category': 'real_estate', 'boat', 'product' o 'other'.
        5. 'location': Ciudad, provincia o zona (o null).
        6. 'query': Términos clave específicos (o null).
        7. 'price_max': Número entero en euros (o null).
        8. 'price_min': Número entero en euros (o null).
        9. 'property_types': ['homes'], ['lands'], ['premises'] o null.
        10. 'project_name': 'Casa', 'Barco' o 'Producto'.
        """

        prompt = f"Analiza esta petición del usuario: '{user_prompt}' y responde únicamente con el objeto JSON."

        models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
        for m in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                    ),
                )
                data = json.loads(response.text)

                cat = ItemCategory.OTHER
                try:
                    cat = ItemCategory(data.get("category", "other"))
                except ValueError:
                    pass

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
            except Exception as e:
                logger.warning("Fallo en consult_and_parse con modelo %s: %s", m, e)

        return {
            "criteria": SearchCriteria(query=user_prompt),
            "project_name": "General",
            "topic_title": f"🔍 {user_prompt[:25]}",
            "tags": ["#Búsqueda"],
            "advice": "Rastreando portales en tiempo real...",
        }

    async def parse_user_request(self, user_prompt: str) -> tuple[SearchCriteria, str]:
        """Compatibilidad hacia atrás con llamadas directas."""
        res = await self.consult_and_parse(user_prompt)
        return res["criteria"], res["project_name"]


    async def generate_weekly_report(self, top_opportunities: list[dict[str, Any]]) -> str:
        """Genera un análisis ejecutivo semanal de las mejores oportunidades."""
        if not self.is_available:
            return "Aquí tienes las oportunidades destacadas de la semana."

        prompt = f"""
        Actúa como un asesor experto de inversiones y compras de oportunidad.
        Analiza las siguientes oportunidades encontradas esta semana y redacta un resumen ejecutivo en formato Telegram Markdown:
        - Destaca los 2-3 mejores chollos.
        - Explica brevemente por qué son buenas inversiones o compras.
        - Da una recomendación de negociación (ej. qué oferta hacer).

        Datos de las oportunidades:
        {json.dumps(top_opportunities[:5], ensure_ascii=False, indent=2)}
        """

        models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
        for m in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=m,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                logger.warning("Fallo reporte con modelo %s: %s", m, e)

        return "No se pudo generar el reporte con IA."

