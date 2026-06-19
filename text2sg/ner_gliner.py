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


def load_model(model_name: str = DEFAULT_MODEL, device: str | None = None):
    """Carga GLiNER (descarga de HuggingFace la primera vez) y lo mueve a GPU si hay.
    `device` fuerza 'cuda'/'cpu'; por defecto autodetecta CUDA."""
    import torch
    from gliner import GLiNER

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return GLiNER.from_pretrained(model_name).to(dev)


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


def _merge(seen: dict, raw_text: str, label: str, score: float, body: str) -> None:
    """Acumula una mención en `seen`, dedup por (texto.lower, tipo) guardando el mejor
    score y el char_span de la primera aparición en el body. Muta `seen` in-place."""
    text = raw_text.strip()
    if not text:
        return
    etype = LABELS_ES.get(label, label)
    key = (text.lower(), etype)
    score = round(float(score), 3)
    if key not in seen or score > seen[key]["score"]:
        span = body.find(text)
        seen[key] = {
            "text": text,
            "type": etype,
            "score": score,
            "char_span": [span, span + len(text)] if span >= 0 else None,
        }


def extract_article(
    model,
    article_id: str,
    body: str,
    *,
    labels: list[str] | None = None,
    threshold: float = 0.4,
) -> dict[str, Any]:
    """Extrae menciones tipadas de UN artículo (camino 1×1, sin batching)."""
    label_keys = labels or list(LABELS_ES.keys())
    seen: dict[tuple[str, str], dict] = {}
    for chunk, _off in _chunks(body):
        for ent in model.predict_entities(chunk, label_keys, threshold=threshold):
            _merge(seen, ent["text"], ent["label"], ent["score"], body)
    return {"article_id": article_id, "entities": list(seen.values())}


def extract_batch(
    model,
    items: list[tuple[str, str]],
    *,
    labels: list[str] | None = None,
    threshold: float = 0.4,
) -> list[dict]:
    """Extrae menciones de un lote de artículos aprovechando la GPU: aplana TODOS los
    chunks del lote en una sola llamada `batch_predict_entities` y reagrupa por artículo.

    `items`: lista de (article_id, body). Devuelve un dict por artículo, en el mismo orden.
    """
    label_keys = labels or list(LABELS_ES.keys())
    flat_texts: list[str] = []
    owner: list[int] = []  # índice del artículo dueño de cada chunk
    for idx, (_aid, body) in enumerate(items):
        for chunk, _off in _chunks(body):
            flat_texts.append(chunk)
            owner.append(idx)
    if not flat_texts:
        return [{"article_id": aid, "entities": []} for aid, _ in items]

    preds = model.batch_predict_entities(flat_texts, label_keys, threshold=threshold)
    seens: list[dict] = [dict() for _ in items]
    for tix, ents in enumerate(preds):
        idx = owner[tix]
        body = items[idx][1]
        for ent in ents:
            _merge(seens[idx], ent["text"], ent["label"], ent["score"], body)
    return [
        {"article_id": items[i][0], "entities": list(seens[i].values())}
        for i in range(len(items))
    ]


def run(
    df: pd.DataFrame,
    model=None,
    *,
    labels: list[str] | None = None,
    threshold: float = 0.4,
    batch_size: int = 16,
    model_name: str = DEFAULT_MODEL,
) -> list[dict]:
    """Corre GLiNER sobre un DataFrame (`article_id`, `body`) en lotes (GPU-friendly)."""
    model = model or load_model(model_name)
    rows = list(df[["article_id", "body"]].itertuples(index=False, name=None))
    out: list[dict] = []
    for start in range(0, len(rows), batch_size):
        out.extend(extract_batch(model, rows[start : start + batch_size],
                                 labels=labels, threshold=threshold))
    return out
