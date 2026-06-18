"""NER pass: detecta entidades y sus aliases en artículos chilenos.

Arquitectura:
  - 1 llamada LLM por artículo (modelo liviano: Gemini flash-lite o Haiku)
  - Output: {canonical, type, role, surface_forms[]} por entidad
  - Scope: TODAS las entidades relevantes, no solo actores políticos estrictos

Para uso en-sesión con Haiku (sin API key):
  Ver workflows/haiku_ner_discovery.workflow.js

Para uso en producción con Gemini Batch API:
  Ver scripts/batch_gemini.py (pendiente)
"""
from __future__ import annotations

import json
from typing import Any

NER_SYSTEM_PROMPT = """Sos un extractor de entidades para noticias chilenas.
Identificá TODAS las entidades nombradas relevantes: personas, partidos, instituciones,
coaliciones, movimientos, organizaciones, empresas, medios, etc.

Para CADA entidad:
1. Identificá el nombre CANÓNICO más completo que aparece en el texto.
2. Listá TODAS las formas en que el artículo se refiere a ella (surface_forms),
   incluyendo cargos/títulos, pronombres contextuales y apodos.
3. Tipificá: person / party / institution / coalition / movement / org / location / other
4. Si podés inferir el rol o cargo del contexto, incluyelo en "role".

IMPORTANTE: El objetivo es construir un diccionario de aliases.
Es mejor incluir de más que de menos."""

NER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "article_id": {"type": "string"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string"},
                    "type": {"type": "string",
                             "enum": ["person", "party", "institution", "coalition",
                                      "movement", "org", "location", "other"]},
                    "role": {"type": "string"},
                    "surface_forms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["canonical", "type", "surface_forms"],
            },
        },
    },
    "required": ["article_id", "entities"],
}


def build_ner_prompt(article_id: str, body: str) -> str:
    """Construye el prompt NER para un artículo."""
    return (
        f"ARTÍCULO {article_id}:\n{body}\n\n"
        "Extraé todas las entidades con sus aliases según las instrucciones del sistema.\n"
        f'Devolvé: {{"article_id": "{article_id}", "entities": [...]}}'
    )


def parse_ner_response(response_text: str) -> dict[str, Any]:
    """Parsea la respuesta JSON del modelo NER."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return json.loads(text)


def aggregate_entities(ner_results: list[dict]) -> list[dict]:
    """Agrega entidades de múltiples artículos, fusionando aliases.

    Fusión conservadora: solo si hay solapamiento claro de surface_forms
    o si un canonical está contenido en el otro.
    """
    canonical_map: dict[str, dict] = {}

    for result in ner_results:
        for entity in result.get("entities", []):
            canonical = entity["canonical"].strip()
            sf_set = set(f.strip() for f in entity.get("surface_forms", []))
            sf_set.add(canonical)

            # Buscar si ya existe una entrada que se solape
            matched_key = None
            for key, existing in canonical_map.items():
                existing_sf = set(existing["surface_forms"])
                # Solapamiento directo o substring
                if sf_set & existing_sf or key in canonical or canonical in key:
                    matched_key = key
                    break

            if matched_key:
                # Fusionar: usar el canonical más largo, unir surface_forms
                existing = canonical_map[matched_key]
                merged_canonical = (
                    canonical if len(canonical) > len(matched_key) else matched_key
                )
                existing["surface_forms"] = list(
                    set(existing["surface_forms"]) | sf_set
                )
                existing["n_articles"] = existing.get("n_articles", 1) + 1
                if merged_canonical != matched_key:
                    canonical_map[merged_canonical] = canonical_map.pop(matched_key)
                    canonical_map[merged_canonical]["canonical"] = merged_canonical
            else:
                canonical_map[canonical] = {
                    "canonical": canonical,
                    "type": entity.get("type", "other"),
                    "role": entity.get("role"),
                    "surface_forms": list(sf_set),
                    "n_articles": 1,
                }

    result_list = sorted(
        canonical_map.values(), key=lambda x: x["n_articles"], reverse=True
    )
    return result_list
