"""Materializa el corpus político pre-filtrado (gazetteer + léxico) del lake a un parquet.

Reproduce la muestra de 80k (`--limit 80000`) o el corpus político COMPLETO de la
ventana de análisis (`--limit` omitido → ~383.675 art para 2019-2022). Muestreo
reproducible por `hash(article_id || seed)`, así que la 80k es subconjunto del full.

El NER (`run_ner_gliner.py --source <este parquet> --fp16`) resume por article_id:
apuntarlo al full salta los 80k ya extraídos y procesa solo el resto.

Uso:
    python scripts/build_political_sample.py                       # full 2019-2022 (~383k)
    python scripts/build_political_sample.py --limit 80000         # reproduce la muestra 80k
    python scripts/build_political_sample.py --out data/processed/samples/political_full.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LAKE = ROOT / "data/raw/corpus/news/articles"
GAZETTEER = ROOT / "data/processed/gazetteer.json"
DEFAULT_OUT = ROOT / "data/processed/samples/political_2019_2022_full.parquet"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default=str(LAKE))
    ap.add_argument("--gazetteer", default=str(GAZETTEER))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--year-range", type=int, nargs=2, default=[2019, 2022])
    ap.add_argument("--min-actors", type=int, default=2)
    ap.add_argument("--min-lexicon-hits", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="omitir = corpus completo")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from text2sg.corpus_data import build_political_lexicon, load_political_articles

    gaz = json.loads(Path(args.gazetteer).read_text(encoding="utf-8"))
    lex = build_political_lexicon()
    yr = tuple(args.year_range)
    print(f"Lake: {args.lake} | año {yr[0]}-{yr[1]} | gaz {len(gaz)} | "
          f"OR(actors≥{args.min_actors}, lex≥{args.min_lexicon_hits}) | "
          f"limit {args.limit or 'FULL'}", flush=True)

    t0 = time.time()
    df = load_political_articles(
        args.lake, gaz, lexicon=lex,
        year_range=yr, min_actors=args.min_actors,
        min_lexicon_hits=args.min_lexicon_hits,
        limit=args.limit, seed=args.seed,
    )
    print(f"Filtrado: {len(df):,} artículos en {time.time()-t0:.0f}s", flush=True)

    # listas (matched_*) a JSON-string → parquet portable; year a int
    for col in ("matched_actors", "matched_lexicon"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: json.dumps(list(v), ensure_ascii=False)
                                    if v is not None else "[]")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    by_year = df.groupby("year").size().to_dict()
    print(f"Escrito: {out}  ({out.stat().st_size/1e6:.0f} MB)")
    print("Por año:", {int(k): int(v) for k, v in sorted(by_year.items())})


if __name__ == "__main__":
    main()
