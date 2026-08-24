"""Módulo de Inteligencia Artificial para HunterBot con asesores especializados por materia."""

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
    """Asesor inteligente hiper-especializado por vertical (Náutica, Inmobiliaria, Tecnología/Consumo)."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or _get_default_key()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call_model(self, system_instruction: str, user_content: str) -> str:
        """Ejecuta una petición REST al modelo garantizando respuestas en español e instrucciones de rol."""
        for model_name in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={self.api_key}"
            )
            # Enviar el rol y la consulta de forma estructurada
            prompt = (
                f"INSTRUCCIONES DEL ASESOR:\n{system_instruction}\n\n"
                f"IDIOMA OBLIGATORIO: ESPAÑOL DE ESPAÑA (No uses inglés bajo ninguna circunstancia).\n\n"
                f"CONSULTA:\n{user_content}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 2500,
                    "responseMimeType": "application/json",
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
                            # Extraer el contenido redactado real descartando notas internas de razonamiento en inglés
                            lines = text.split("\n")
                            clean_lines = []
                            meta_pattern = re.compile(
                                r"^\s*[*•-]?\s*(?:Subject|Role|Mission|Value|Purpose|Format|Structure|Language|Constraint|Rules|Input|Drafting|Paragraph \d|Step \d|Direct response|Task|Context|Checklist|Item \d):",
                                re.IGNORECASE,
                            )
                            for line in lines:
                                stripped = line.strip()
                                if not stripped:
                                    continue
                                if meta_pattern.match(stripped):
                                    continue
                                if stripped.startswith("*   *") and ":" in stripped:
                                    continue
                                clean_l = line.lstrip(" \t*•-")
                                if len(clean_l) > 15:
                                    clean_lines.append(clean_l)

                            cleaned_text = "\n\n".join(clean_lines).strip()
                            if cleaned_text:
                                logger.info("IA respondió con modelo %s (%d chars)", model_name, len(cleaned_text))
                                return cleaned_text
                            return text.strip()
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
        """Clasifica la búsqueda y genera el asesoramiento inicial adaptado a la materia."""
        system_instruction = (
            "Eres el director del equipo de asesores de HunterBot. Tu trabajo es interpretar la búsqueda "
            "y redactar un asesoramiento de entrada de alto nivel técnico en ESPAÑOL.\n"
            "- Si es Náutica (barco, velero, lancha, semirrígida Zar/Beneteau/etc.): Actúa como Capitán y perito naval (casco, eslora, motor fueraborda/intraborda, estado de flotadores Hypalon, titulación PER/PNB).\n"
            "- Si es Inmobiliaria (terreno, finca, parcela, casa, piso): Actúa como Arquitecto y consultor inmobiliario (suelo rústico/urbano, edificabilidad, acceso rodado, agua/luz, registro de la propiedad).\n"
            "- Si es Producto/Tecnología/Deporte (ordenador, zapatillas, móvil): Actúa como Consultor técnico de compras (gama, procesador/RAM, amortiguación/pisada, histórico de precios, mejor época de compra).\n"
            "Devuelve ÚNICAMENTE un JSON válido con la siguiente estructura:"
        )

        user_content = (
            f"Consulta del usuario: '{user_prompt}'\n\n"
            "Estructura JSON requerida:\n"
            "{\n"
            '  "topic_title": "emoji + Título conciso en español (máx 35 caracteres)",\n'
            '  "tags": ["#Etiqueta1", "#Etiqueta2", "#Etiqueta3"],\n'
            '  "advice": "Diagnóstico de mercado detallado y profesional en español de España: rangos de precios razonables según modelo/zona, puntos clave a inspeccionar y recomendación para acertar.",\n'
            '  "category": "real_estate" | "boat" | "product",\n'
            '  "location": "Municipio o zona en España" o null,\n'
            '  "query": "Términos exactos a buscar" o null,\n'
            '  "price_max": número o null,\n'
            '  "price_min": número o null,\n'
            '  "property_types": ["lands"] | ["homes"] | ["premises"] o null,\n'
            '  "project_name": "Barco" | "Casa" | "Producto"\n'
            "}"
        )

        raw_resp = self._call_model(system_instruction, user_content)
        data = self._extract_json(raw_resp)

        if not data:
            logger.warning("IA no devolvió JSON válido. Usando fallback especializado.")
            return self._fallback_consult(user_prompt)

        cat = self._map_category(data.get("category", "other"))
        clean_q = data.get("query")
        if clean_q:
            # Eliminar URLs o frases conversacionales largas del query para los buscadores
            clean_q = re.sub(r"https?://\S+", "", clean_q)
            clean_q = re.sub(r"^(?:búscame|buscame|encuéntrame|encuentrame|quiero|necesito|según tu opinión|segun tu opinion|en esta página|en esta pagina)\s*", "", clean_q, flags=re.IGNORECASE).strip()
        if not clean_q or len(clean_q) < 3:
            clean_q = "barcos remolcables" if cat == ItemCategory.BOAT else "oportunidades"

        criteria = SearchCriteria(
            category=cat,
            location=data.get("location"),
            query=clean_q,
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
        """Analiza los resultados encontrados y da una recomendación rigurosa en español según la vertical."""
        if not results:
            return ""

        if not self.is_available:
            return self._basic_analysis(results)

        items_summary = []
        for r in results[:8]:
            title = r.get("title", "Barco")
            price = f"{r.get('price', 0):,.0f} €" if r.get("price", 0) > 0 else "Consultar precio"
            length = f"Eslora: {r.get('length_m')}m" if r.get("length_m") else ""
            desc = r.get("raw_text") or r.get("description_raw") or ""
            items_summary.append(f"- {title} ({price}, {length}): {desc[:120]}")

        summary_text = "\n".join(items_summary)

        system_instruction = (
            "Eres un Perito Naval y Asesor de Compras senior en España.\n"
            "Tu tarea es evaluar las ofertas encontradas y dar un dictamen técnico al comprador.\n"
            "IDIOMA: Responde exclusivamente en ESPAÑOL DE ESPAÑA.\n"
            "REGLA CRÍTICA: NO INCLUYAS NINGÚN RAZONAMIENTO, NOTA, BORRADOR, NI TEXTO EN INGLÉS.\n"
            "EL PRIMER CARÁCTER DE TU RESPUESTA DEBE SER EXACTAMENTE `{`.\n"
            "Devuelve ÚNICAMENTE un JSON válido con la siguiente estructura:\n"
            "{\n"
            '  "mejor_eleccion": "🏆 MEJOR ELECCIÓN: (Indica cuál es el mejor barco remolcable calidad-precio y por qué)",\n'
            '  "detalles_tecnicos": "🔍 DETALLES TÉCNICOS: (Eslora, manga máxima legal de 2,55m para remolque, peso y motor)",\n'
            '  "riesgos_gastos": "⚠️ RIESGOS Y GASTOS: (Remolque no incluido, ITB, seguro, revisión de motor)",\n'
            '  "precio_negociacion": "🎯 PRECIO DE NEGOCIACIÓN: (Recomendación de oferta a la baja)"\n'
            "}"
        )

        user_content = (
            f"Consulta del comprador: '{user_query}'\n\n"
            f"Barcos encontrados en el catálogo:\n{summary_text}\n\n"
            "Escribe tu dictamen en español directamente en formato JSON:"
        )

        resp = self._call_model(system_instruction, user_content)
        if resp:
            # Intentar extraer el JSON de la respuesta
            json_match = re.search(r"\{.*\}", resp.replace("\n", " "), re.IGNORECASE)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    clean_resp = (
                        f"{data.get('mejor_eleccion', '')}\n\n"
                        f"{data.get('detalles_tecnicos', '')}\n\n"
                        f"{data.get('riesgos_gastos', '')}\n\n"
                        f"{data.get('precio_negociacion', '')}"
                    ).replace("**", "").replace("__", "").replace("```", "").strip()
                    return clean_resp[:2000]
                except json.JSONDecodeError:
                    pass
            
            # Fallback: Extraer líneas con emojis si el JSON falla
            fallback_lines = []
            for line in resp.split("\n"):
                if any(e in line for e in ["🏆", "🔍", "⚠️", "🎯"]) or (fallback_lines and line.strip()):
                    # Detenernos si empieza otro bloque de notas (Gemma artifact)
                    if re.match(r"^\s*[*•-]?\s*(?:Subject|Role|Mission|Constraint|Drafting):", line, re.IGNORECASE):
                        break
                    fallback_lines.append(line)
            
            if fallback_lines:
                return "\n".join(fallback_lines).replace("**", "").replace("__", "").strip()[:2000]

            clean_resp = resp.replace("**", "").replace("__", "").replace("```", "").strip()
            return clean_resp[:1200]
        return self._basic_analysis(results)

    async def chat_followup(self, user_query: str, context: str) -> str:
        """Responde a preguntas de seguimiento del usuario actuando como asesor especializado."""
        if not self.is_available:
            return "No hay conexión con el servicio de IA en este momento."

        system_instruction = (
            "Eres el Asesor Especialista de HunterBot en conversación con el usuario.\n"
            "Responde a su duda con criterio profesional, buscando siempre lo que más le conviene al comprador.\n"
            "REGLAS:\n"
            "1. Responde obligatoriamente en ESPAÑOL DE ESPAÑA.\n"
            "2. Proporciona argumentos técnicos y de precio sólidos.\n"
            "3. Máximo 600 caracteres.\n"
            "4. Sin asteriscos de Markdown."
        )

        user_content = (
            f"Contexto previo de la búsqueda y ofertas:\n{context}\n\n"
            f"Pregunta del usuario: '{user_query}'\n\n"
            "Tu respuesta como asesor experto:"
        )

        resp = self._call_model(system_instruction, user_content)
        if resp:
            return resp.replace("**", "").replace("__", "").replace("```", "").strip()[:800]
        return "No he podido procesar tu consulta en este momento."

    def _basic_analysis(self, results: list[dict[str, Any]]) -> str:
        """Análisis básico de respaldo con precios."""
        if not results:
            return ""
        prices = [r["price"] for r in results if r.get("price", 0) > 0]
        if not prices:
            return "📊 Consulta los enlaces anteriores para comparar las características completas de cada opción."
        avg = sum(prices) / len(prices)
        cheapest = min(prices)
        return (
            f"📊 Resumen de mercado: {len(results)} opciones indexadas.\n"
            f"💰 Precio medio aproximado: {avg:,.0f} €\n"
            f"🔥 Opción más accesible: {cheapest:,.0f} €\n"
            f"💡 Revisa las condiciones particulares de cada ficha antes de formalizar la compra."
        ).replace(",", ".")

    @staticmethod
    def _map_category(cat_str: str) -> ItemCategory:
        cat_lower = (cat_str or "other").lower()
        if "estate" in cat_lower or "real" in cat_lower or "terreno" in cat_lower or "inmob" in cat_lower:
            return ItemCategory.REAL_ESTATE
        if "boat" in cat_lower or "barco" in cat_lower or "nautic" in cat_lower:
            return ItemCategory.BOAT
        if "product" in cat_lower or "item" in cat_lower or "zapat" in cat_lower or "ordenad" in cat_lower:
            return ItemCategory.PRODUCT
        return ItemCategory.PRODUCT

    @staticmethod
    def _default_project(cat: ItemCategory) -> str:
        if cat == ItemCategory.REAL_ESTATE:
            return "Inmobiliaria"
        if cat == ItemCategory.BOAT:
            return "Náutica"
        return "Compras"

    def _fallback_consult(self, user_prompt: str) -> dict[str, Any]:
        """Fallback inteligente en español si la IA no responde."""
        lower = user_prompt.lower()
        cat = ItemCategory.PRODUCT
        prop_types = None
        query = user_prompt

        land_words = ["terreno", "parcela", "finca", "solar", "rústic", "rural"]
        home_words = ["casa", "piso", "chalet", "ático", "vivienda", "apartamento", "dúplex", "adosado"]
        premises_words = ["local", "oficina", "nave", "garaje", "trastero"]
        boat_words = ["barco", "velero", "lancha", "yate", "catamaran", "embarcación",
                       "zar", "formenti", "beneteau", "jeanneau", "bavaria", "hanse",
                       "dufour", "lagoon", "fountaine", "zodiac", "quicksilver", "semirrigida"]

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
            "advice": "Rastreando portales especializados en tiempo real...",
        }
