"""Top-up proporcional — agrega los artículos que faltan para llegar a 480k en 2014-2026.

Reutiliza los 228k ya muestreados (3×80k). Por año, carga el pool político completo,
EXCLUYE los article_id ya muestreados, y toma los `faltan[año]` nuevos (hash-ordenado,
reproducible). El target por año es proporcional al volumen político disponible.

Salida: una muestra parquet con los ~251k artículos nuevos → NER (resume) → ER/RE/graph
sobre las 4 muestras (3 viejas + esta).

Uso: python scripts/build_topup_sample.py --out data/processed/samples/political_topup_251k.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LAKE = ROOT / "data/raw/corpus/news/articles"
GAZETTEER = ROOT / "data/processed/gazetteer.json"
SAMPLES = ["political_2014_2018_80k", "political_2019_2022_80k", "political_2022_2026_80k"]

# faltan[año] para llegar a 480k proporcional (medido 2026-06-23, ver saturation.py + measure)
FALTAN = {2014: 3921, 2015: 6613, 2016: 17283, 2017: 16079, 2018: 10423, 2019: 21229,
          2020: 27363, 2021: 33444, 2022: 20644, 2023: 24146, 2024: 26375, 2025: 28817, 2026: 15001}


def hrank(aid: str, seed: int) -> int:
    return int(hashlib.md5(f"{aid}{seed}".encode()).hexdigest()[:12], 16)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/processed/samples/political_topup_251k.parquet"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import pandas as pd
    from text2sg.corpus_data import build_political_lexicon, load_political_articles

    # ya muestreados (a excluir)
    existing = set()
    for s in SAMPLES:
        existing |= set(pd.read_parquet(ROOT / f"data/processed/samples/{s}.parquet",
                                        columns=["article_id"])["article_id"])
    print(f"ya muestreados (excluir): {len(existing):,}", flush=True)

    gaz = json.loads(Path(GAZETTEER).read_text(encoding="utf-8"))
    lex = build_political_lexicon()

    parts = []
    t0 = time.time()
    for y in sorted(FALTAN):
        need = FALTAN[y]
        pool = load_political_articles(str(LAKE), gaz, lexicon=lex, year_range=(y, y),
                                       min_actors=2, min_lexicon_hits=3, limit=None, seed=args.seed)
        pool = pool[~pool["article_id"].isin(existing)].copy()
        pool["_h"] = pool["article_id"].map(lambda a: hrank(a, args.seed))
        take = pool.sort_values("_h").head(need).drop(columns="_h")
        parts.append(take)
        print(f"  {y}: pool nuevo {len(pool):,} | tomados {len(take):,}/{need:,}", flush=True)

    df = pd.concat(parts, ignore_index=True)
    for col in ("matched_actors", "matched_lexicon"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: json.dumps(list(v), ensure_ascii=False) if v is not None else "[]")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\nTop-up: {len(df):,} artículos nuevos en {time.time()-t0:.0f}s → {out} ({out.stat().st_size/1e6:.0f} MB)")
    print("Por año:", {int(k): int(v) for k, v in sorted(df.groupby('year').size().items())})


if __name__ == "__main__":
    main()
