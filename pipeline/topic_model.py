"""Pipeline de modelado temático sobre el corpus político.

Flujo:
  1. Cargar artículos políticos (filtro OR: gazetteer + léxico, todos los años).
  2. Embedear title + body[:600] con sentence-transformers en GPU.
     Checkpointing a .npy — si se interrumpe, continúa desde donde quedó.
  3. Ajustar BERTopic → descubre tópicos naturales (sin taxonomía impuesta).
  4. Exportar asignaciones (article_id → topic_id + label) a Parquet.
  5. Generar reporte de top-keywords por tópico para revisión manual.

Los tópicos descubiertos se convierten en el vocabulario restringido del prompt
inline de extracción (Artefacto A del genoma). No se hardcodean.

Uso:
    python text2sg/scripts/build_topic_model.py \\
        --lake text2sg/results/corpus/news/articles \\
        --gazetteer text2sg/results/corpus/gazetteer.json \\
        --out text2sg/results/corpus/topics \\
        [--limit 200000]   # opcional: muestra para fit rápido
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Texto a embedear ───────────────────────────────────────────────────────── #

BODY_CHARS = 600  # chars del body (captura el tema sin llenar VRAM)


def _embed_text(row: pd.Series) -> str:
    title = str(row.get("title") or "")
    body = str(row.get("body") or "")[:BODY_CHARS]
    return (title + " " + body).strip()


# ── Embeddings con checkpointing ───────────────────────────────────────────── #

def build_embeddings(
    df: pd.DataFrame,
    out_dir: Path,
    *,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    batch_size: int = 512,
    device: str | None = None,
) -> np.ndarray:
    """Embedea `df` y guarda en `out_dir/embeddings.npy` + `out_dir/ids.npy`.

    Si el checkpoint ya existe y tiene la misma cantidad de filas, lo devuelve
    directamente (idempotente). Progreso en stdout cada 10k artículos.
    """
    from sentence_transformers import SentenceTransformer
    import torch

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emb_path = out_dir / "embeddings.npy"
    ids_path = out_dir / "ids.npy"

    if emb_path.exists() and ids_path.exists():
        emb = np.load(emb_path)
        if emb.shape[0] == len(df):
            log.info("Checkpoint existente (%d docs) — cargando.", emb.shape[0])
            return emb

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Embeddding %d artículos en %s (batch=%d)…", len(df), device, batch_size)

    model = SentenceTransformer(model_name, device=device)
    texts = df.apply(_embed_text, axis=1).tolist()
    emb = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    np.save(emb_path, emb)
    np.save(ids_path, df["article_id"].values)
    log.info("Embeddings guardados → %s (%s MB)", emb_path,
             round(emb.nbytes / 1e6, 1))
    return emb


# ── Ajuste BERTopic ────────────────────────────────────────────────────────── #

def fit_topic_model(
    df: pd.DataFrame,
    embeddings: np.ndarray,
    out_dir: Path,
    *,
    min_topic_size: int = 80,
    nr_topics: int | str = "auto",
    language: str = "spanish",
) -> tuple:
    """Ajusta BERTopic sobre los embeddings y devuelve (model, topics, probs).

    Guarda el modelo en `out_dir/bertopic_model/`.
    """
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    out_dir = Path(out_dir)

    umap_model = UMAP(
        n_neighbors=15,
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        min_samples=10,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    # CountVectorizer bilingüe (el corpus mezcla inglés/español en prompts)
    vectorizer = CountVectorizer(
        ngram_range=(1, 2),
        stop_words=_spanish_stopwords(),
        min_df=5,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        language=language,
        nr_topics=nr_topics,
        calculate_probabilities=False,
        verbose=True,
    )
    texts = df.apply(_embed_text, axis=1).tolist()
    topics, _ = topic_model.fit_transform(texts, embeddings)
    topic_model.save(str(out_dir / "bertopic_model"), serialization="safetensors",
                     save_ctfidf=True, save_embedding_model=False)
    return topic_model, topics


# ── Exportar asignaciones ──────────────────────────────────────────────────── #

def export_topic_assignments(
    df: pd.DataFrame,
    topics: list[int],
    topic_model,
    out_dir: Path,
) -> pd.DataFrame:
    """Guarda `article_id → topic_id, topic_label, top_words` en Parquet."""
    out_dir = Path(out_dir)
    topic_info = topic_model.get_topic_info()
    label_map = {
        row["Topic"]: row["Name"]
        for _, row in topic_info.iterrows()
    }
    out = df[["article_id", "year", "publish_date"]].copy()
    out["topic_id"] = topics
    out["topic_label"] = [label_map.get(t, "outlier") for t in topics]
    pq_path = out_dir / "topic_assignments.parquet"
    out.to_parquet(pq_path, index=False)
    log.info("Asignaciones guardadas → %s (%d filas)", pq_path, len(out))
    return out


# ── Reporte para revisión manual ───────────────────────────────────────────── #

def topic_report(
    topic_model,
    assignments: pd.DataFrame,
    out_path: Path | None = None,
) -> str:
    """Genera tabla de tópicos con top-keywords y frecuencias.

    La tabla se usa para decidir manualmente el mapping topic_id → macro_topic.
    """
    info = topic_model.get_topic_info().sort_values("Count", ascending=False)
    lines = ["# Tópicos descubiertos por BERTopic\n",
             "Revisá esta tabla y completá la columna `macro_topic` en "
             "`topic_macro_mapping.json`.\n",
             f"| topic_id | count | % | top_keywords | macro_topic |",
             "|---|---|---|---|---|"]
    total = len(assignments)
    for _, row in info.iterrows():
        tid = row["Topic"]
        if tid == -1:
            label = "OUTLIER"
        else:
            keywords = " · ".join(
                w for w, _ in topic_model.get_topic(tid)[:8]
            )
            n = row["Count"]
            pct = n / total * 100
            lines.append(f"| {tid} | {n:,} | {pct:.1f}% | {keywords} | ??? |")

    report = "\n".join(lines)
    if out_path:
        Path(out_path).write_text(report, encoding="utf-8")
        log.info("Reporte → %s", out_path)
    return report


def build_macro_mapping_template(topic_model, out_path: Path) -> None:
    """Genera `topic_macro_mapping.json` con entradas vacías para completar."""
    info = topic_model.get_topic_info()
    mapping = {}
    for _, row in info.iterrows():
        tid = row["Topic"]
        if tid == -1:
            continue
        keywords = [w for w, _ in topic_model.get_topic(tid)[:5]]
        mapping[str(tid)] = {
            "keywords": keywords,
            "macro_topic": "",   # ← completar a mano
            "count": int(row["Count"]),
        }
    Path(out_path).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Template macro-mapping → %s (%d tópicos)", out_path, len(mapping))


def load_macro_mapping(path: Path) -> dict[int, str]:
    """Carga `topic_macro_mapping.json` → {topic_id: macro_topic}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(k): v["macro_topic"] for k, v in raw.items() if v["macro_topic"]}


# ── Inferencia sobre artículos nuevos ─────────────────────────────────────── #

def assign_topics_to_new(
    df: pd.DataFrame,
    topic_model,
    macro_mapping: dict[int, str],
    *,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    batch_size: int = 512,
    device: str | None = None,
) -> pd.DataFrame:
    """Asigna tópicos a artículos nuevos usando el modelo ya ajustado.

    Más rápido que fit_transform (solo inferencia, sin re-ajustar UMAP/HDBSCAN).
    """
    import torch
    from sentence_transformers import SentenceTransformer

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(model_name, device=device)
    texts = df.apply(_embed_text, axis=1).tolist()
    emb = model.encode(texts, batch_size=batch_size, show_progress_bar=True,
                       convert_to_numpy=True)
    topics, _ = topic_model.transform(texts, emb)
    out = df[["article_id"]].copy()
    out["topic_id"] = topics
    out["macro_topic"] = [macro_mapping.get(t, "otro") for t in topics]
    return out


# ── Stop words español ─────────────────────────────────────────────────────── #

def _spanish_stopwords() -> list[str]:
    return [
        "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las",
        "por", "un", "para", "con", "no", "una", "su", "al", "lo", "como",
        "más", "pero", "sus", "le", "ya", "o", "este", "sí", "porque", "esta",
        "entre", "cuando", "muy", "sin", "sobre", "también", "me", "hasta",
        "hay", "donde", "quien", "desde", "todo", "nos", "durante", "todos",
        "uno", "les", "ni", "contra", "otros", "ese", "eso", "ante", "ellos",
        "e", "esto", "mí", "antes", "algunos", "qué", "unos", "yo", "otro",
        "otras", "era", "este", "ha", "ha", "han", "fue", "ser", "dijo",
        "señaló", "indicó", "agregó", "explicó", "aseguró", "afirmó",
    ]
