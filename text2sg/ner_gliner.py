"""NER con GLiNER (zero-shot, local, $0) — Pasada 1 del pipeline de grafo.

GLiNER solo DETECTA menciones tipadas: (text, type, score, char_span). NO produce
canonical/aliases/role — eso se construye en la Pasada 2 (ER). El objetivo de esta
pasada es la detección masiva determinista sobre los 80k sin gastar LLM.

Bodies largos se trocean por ventanas de palabras con solapamiento (GLiNER tiene un
límite de contexto ~384 tokens); las menciones se deduplican por (texto, tipo).

Uso:
    from text2sg.ner_gliner import load_model, run
    model = load_model()
    results = run(df[["article_id", "body"]], model)   # df con article_id + body
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

# Taxonomía interna (person/party/institution/coalition/movement/org) ← labels GLiNER.
# GLiNER es zero-shot y sensible al wording de las labels: las damos en español
# (corpus chileno) y mapeamos al tipo canónico del esquema de nodos.
LABELS_ES: dict[str, str] = {
    "persona": "person",
    "partido político": "party",
    "institución pública": "institution",
    "coalición política": "coalition",
    "pacto electoral": "coalition",
    "alianza política": "coalition",
    "movimiento social": "movement",
    "movimiento ciudadano": "movement",
    "organización": "org",
}

DEFAULT_MODEL = "urchade/gliner_multi-v2.1"


def load_model(model_name: str = DEFAULT_MODEL):
    """Carga el modelo GLiNER (descarga de HuggingFace la primera vez)."""
    from gliner import GLiNER

    return GLiNER.from_pretrained(model_name)


def _chunks(text: str, max_words: int = 300, overlap: int = 30) -> Iterable[tuple[str, int]]:
    """Trocea por ventanas de palabras con solapamiento. Devuelve (chunk, word_offset)."""
    words = text.split()
    if len(words) <= max_words:
        yield text, 0
        return
    i = 0
    step = max_words - overlap
    while i < len(words):
        yield " ".join(words[i : i + max_words]), i
        i += step


def extract_article(
    model,
    article_id: str,
    body: str,
    *,
    labels: list[str] | None = None,
    threshold: float = 0.4,
) -> dict[str, Any]:
    """Extrae menciones tipadas de UN artículo. Dedup por (texto.lower, tipo), guarda
    el mejor score y el char_span de la primera aparición en el body."""
    label_keys = labels or list(LABELS_ES.keys())
    seen: dict[tuple[str, str], dict] = {}
    for chunk, _off in _chunks(body):
        for ent in model.predict_entities(chunk, label_keys, threshold=threshold):
            text = ent["text"].strip()
            if not text:
                continue
            etype = LABELS_ES.get(ent["label"], ent["label"])
            key = (text.lower(), etype)
            score = round(float(ent["score"]), 3)
            if key not in seen or score > seen[key]["score"]:
                span = body.find(text)
                seen[key] = {
                    "text": text,
                    "type": etype,
                    "score": score,
                    "char_span": [span, span + len(text)] if span >= 0 else None,
                }
    return {"article_id": article_id, "entities": list(seen.values())}


def run(
    df: pd.DataFrame,
    model=None,
    *,
    labels: list[str] | None = None,
    threshold: float = 0.4,
    model_name: str = DEFAULT_MODEL,
) -> list[dict]:
    """Corre GLiNER sobre un DataFrame con columnas `article_id` y `body`."""
    model = model or load_model(model_name)
    return [
        extract_article(model, r.article_id, r.body, labels=labels, threshold=threshold)
        for r in df.itertuples()
    ]
