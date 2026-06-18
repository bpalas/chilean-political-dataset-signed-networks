"""Construye el modelo de tópicos BERTopic sobre el corpus político completo.

Uso:
    # Fit sobre todos los artículos políticos (todos los años, OR gazetteer+léxico):
    python text2sg/scripts/build_topic_model.py \\
        --lake text2sg/results/corpus/news/articles \\
        --gazetteer text2sg/results/corpus/gazetteer.json \\
        --out text2sg/results/corpus/topics

    # Con límite (muestra rápida para probar el pipeline):
    python text2sg/scripts/build_topic_model.py ... --limit 50000

    # Solo inferir tópicos sobre artículos nuevos (modelo ya ajustado):
    python text2sg/scripts/build_topic_model.py ... --infer-only

Salidas en --out/:
    embeddings.npy               embeddings de todos los artículos
    ids.npy                      article_ids correspondientes
    bertopic_model/              modelo BERTopic serializado
    topic_assignments.parquet    article_id → topic_id, topic_label, year
    topic_report.md              tabla de tópicos con keywords para revisión
    topic_macro_mapping.json     template para mapear topic_id → macro_topic
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Windows cp1252 → forzar UTF-8 para que los logs con → y ≥ no crasheen
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── path setup ────────────────────────────────────────────────────────────── #
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from text2sg.corpus_data import (  # noqa: E402
    build_political_lexicon,
    load_political_articles,
)
from text2sg.topic_model import (  # noqa: E402
    build_embeddings,
    build_macro_mapping_template,
    export_topic_assignments,
    fit_topic_model,
    topic_report,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--lake", required=True,
                    help="Parquet root: results/corpus/news/articles")
    ap.add_argument("--gazetteer", required=True,
                    help="JSON con lista de actores políticos")
    ap.add_argument("--out", required=True,
                    help="Directorio de salida para embeddings y modelo")
    ap.add_argument("--limit", type=int, default=None,
                    help="Máx artículos a cargar (None = todos)")
    ap.add_argument("--min-actors", type=int, default=2)
    ap.add_argument("--min-lexicon-hits", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--min-topic-size", type=int, default=80,
                    help="Mínimo artículos por tópico BERTopic")
    ap.add_argument("--year-range", nargs=2, type=int, default=None,
                    metavar=("FROM", "TO"),
                    help="Filtrar por año, ej: --year-range 2019 2022")
    ap.add_argument("--infer-only", action="store_true",
                    help="Solo inferir tópicos con modelo ya ajustado")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    gaz = json.loads(Path(args.gazetteer).read_text(encoding="utf-8"))
    lex = build_political_lexicon()
    yr = tuple(args.year_range) if args.year_range else None

    # ── 1. Cargar artículos ─────────────────────────────────────────────── #
    log.info("Cargando artículos políticos (OR: gaz≥%d OR lex≥%d)%s…",
             args.min_actors, args.min_lexicon_hits,
             f" año {yr[0]}–{yr[1]}" if yr else " todos los años")
    df = load_political_articles(
        args.lake, gaz,
        lexicon=lex,
        min_actors=args.min_actors,
        min_lexicon_hits=args.min_lexicon_hits,
        year_range=yr,
        limit=args.limit,
        seed=42,
    )
    log.info("Artículos cargados: %d", len(df))

    if len(df) == 0:
        log.error("Sin artículos — verificar rutas del lago y gazetteer.")
        sys.exit(1)

    if args.infer_only:
        _infer_only(df, out_dir, args)
        return

    # ── 2. Embeddings ───────────────────────────────────────────────────── #
    emb = build_embeddings(df, out_dir, batch_size=args.batch_size)

    # ── 3. BERTopic ─────────────────────────────────────────────────────── #
    log.info("Ajustando BERTopic (min_topic_size=%d)…", args.min_topic_size)
    topic_model, topics = fit_topic_model(
        df, emb, out_dir, min_topic_size=args.min_topic_size
    )
    n_topics = len(set(t for t in topics if t != -1))
    n_outliers = sum(1 for t in topics if t == -1)
    log.info("Tópicos descubiertos: %d | Outliers: %d (%.1f%%)",
             n_topics, n_outliers, n_outliers / len(topics) * 100)

    # ── 4. Exportar asignaciones ────────────────────────────────────────── #
    assignments = export_topic_assignments(df, topics, topic_model, out_dir)

    # ── 5. Reporte y template ───────────────────────────────────────────── #
    report = topic_report(topic_model, assignments,
                          out_path=out_dir / "topic_report.md")
    build_macro_mapping_template(topic_model,
                                 out_dir / "topic_macro_mapping.json")

    # Imprimir top-20 tópicos para revisión rápida en terminal
    print("\n" + "="*60)
    print(f"TÓPICOS DESCUBIERTOS ({n_topics} tópicos + {n_outliers} outliers)")
    print("="*60)
    info = topic_model.get_topic_info().sort_values("Count", ascending=False)
    for _, row in info.head(25).iterrows():
        tid = row["Topic"]
        if tid == -1:
            continue
        kws = ", ".join(w for w, _ in topic_model.get_topic(tid)[:6])
        pct = row["Count"] / len(df) * 100
        print(f"  [{tid:3d}] {row['Count']:6,} ({pct:4.1f}%)  {kws}")
    print(f"\n-> Revisa {out_dir}/topic_report.md")
    print(f"-> Completa macro_topic en {out_dir}/topic_macro_mapping.json")
    print(f"-> Esos macro_topics se usan como vocabulario del prompt inline\n")


def _infer_only(df, out_dir, args):
    from bertopic import BERTopic
    from text2sg.topic_model import assign_topics_to_new, load_macro_mapping
    model_path = out_dir / "bertopic_model"
    if not model_path.exists():
        log.error("Modelo no encontrado en %s — correr sin --infer-only primero.", model_path)
        import sys; sys.exit(1)
    topic_model = BERTopic.load(str(model_path))
    mapping_path = out_dir / "topic_macro_mapping.json"
    macro_mapping = load_macro_mapping(mapping_path) if mapping_path.exists() else {}
    out = assign_topics_to_new(df, topic_model, macro_mapping,
                               batch_size=args.batch_size)
    pq = out_dir / "topic_assignments_new.parquet"
    out.to_parquet(pq, index=False)
    log.info("Asignaciones guardadas → %s", pq)


if __name__ == "__main__":
    main()
