"""Entity Resolution: une aliases entre artículos → IDs canónicos estables.

Pipeline de 4 capas (precision-first):
  1. Gazetteer exacto ($0)         — lookup normalizado, ~80% del volumen
  2. rapidfuzz fuzzy match ($0)    — apellido/token principal, score ≥85%
  3. Splink probabilístico ($0)    — bloqueo + EM, para casos ambiguos
  4. LLM zona gris (flash-lite)    — solo confidence < 0.80 de Splink

Riesgo principal: fusión incorrecta de homónimos.
Mitigación: cross-type blocking + umbral conservador ≥0.90.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional


def normalize(text: str) -> str:
    """Normaliza para lookup: lower, sin acentos, sin puntuación extra."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", text).strip()


class GazetteerIndex:
    """Índice de entidades canónicas con sus aliases normalizados."""

    def __init__(self, gazetteer_path: str | Path):
        self.entries: list[dict] = json.loads(
            Path(gazetteer_path).read_text(encoding="utf-8")
        )
        # Índice: surface_form_normalizada → entity_id
        self._index: dict[str, str] = {}
        for entry in self.entries:
            eid = entry.get("entity_id") or entry.get("canonical")
            for sf in entry.get("aliases", []) + [entry.get("canonical", "")]:
                key = normalize(sf)
                if key:
                    self._index[key] = eid

    def lookup(self, surface_form: str) -> Optional[str]:
        """Lookup exacto normalizado. Retorna entity_id o None."""
        return self._index.get(normalize(surface_form))

    def fuzzy_match(self, surface_form: str, score_cutoff: int = 85) -> Optional[str]:
        """Fuzzy match con rapidfuzz. Requiere: pip install rapidfuzz."""
        try:
            from rapidfuzz import process, fuzz
            key = normalize(surface_form)
            result = process.extractOne(
                key, self._index.keys(),
                scorer=fuzz.token_sort_ratio,
                score_cutoff=score_cutoff,
            )
            if result:
                return self._index[result[0]]
        except ImportError:
            pass
        return None

    def resolve(self, surface_form: str, fuzzy: bool = True) -> Optional[str]:
        """Resolución completa: exacto primero, fuzzy si falla."""
        entity_id = self.lookup(surface_form)
        if entity_id is None and fuzzy:
            entity_id = self.fuzzy_match(surface_form)
        return entity_id


def resolve_batch(
    surface_forms: list[str],
    gazetteer: GazetteerIndex,
) -> dict[str, Optional[str]]:
    """Resuelve una lista de surface_forms. Retorna {sf: entity_id|None}."""
    return {sf: gazetteer.resolve(sf) for sf in surface_forms}
