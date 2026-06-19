"""Pasada 1 a escala — GLiNER NER sobre la muestra de 80k (local, $0).

Checkpointing incremental: shards Parquet particionados por año + state.json
({article_id: done}). Si crashea, al reiniciar omite los ya procesados.

Uso:
    HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner_80k.py            # todo
    HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner_80k.py --limit 500  # smoke

Salida:
    data/processed/ner/gliner/year=YYYY/part-NNNN.parquet   (article_id, entities[json])
    data/processed/ner/gliner/state.json                     ({article_id: "done"})
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from text2sg.ner_gliner import extract_article, load_model  # noqa: E402

SAMPLE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"
OUT = ROOT / "data/processed/ner/gliner"
STATE = OUT / "state.json"
SHARD_SIZE = 2000  # artículos por shard parquet


def load_state() -> set[str]:
    if STATE.exists():
        return set(json.loads(STATE.read_text(encoding="utf-8")).keys())
    return set()


def save_state(done: set[str]) -> None:
    STATE.write_text(json.dumps({a: "done" for a in done}, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="procesar solo N artículos (smoke)")
    ap.add_argument("--threshold", type=float, default=0.4)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(SAMPLE, columns=["article_id", "body", "year"])
    if args.limit:
        df = df.head(args.limit)

    done = load_state()
    todo = df[~df["article_id"].isin(done)].reset_index(drop=True)
    print(f"Total {len(df)} | ya hechos {len(done)} | pendientes {len(todo)}", flush=True)
    if todo.empty:
        print("Nada que hacer.")
        return

    print("Cargando modelo GLiNER...", flush=True)
    model = load_model()

    t0 = time.time()
    buf: list[dict] = []
    shard_year = None
    part = len(list(OUT.rglob("part-*.parquet")))

    def flush(rows: list[dict], year) -> None:
        nonlocal part
        if not rows:
            return
        ydir = OUT / f"year={year}"
        ydir.mkdir(parents=True, exist_ok=True)
        out = pd.DataFrame([{"article_id": r["article_id"],
                             "entities": json.dumps(r["entities"], ensure_ascii=False)} for r in rows])
        out.to_parquet(ydir / f"part-{part:05d}.parquet", index=False)
        part += 1

    for i, r in enumerate(todo.itertuples(), 1):
        res = extract_article(model, r.article_id, r.body, threshold=args.threshold)
        if shard_year is None:
            shard_year = r.year
        if r.year != shard_year or len(buf) >= SHARD_SIZE:
            flush(buf, shard_year)
            buf, shard_year = [], r.year
        buf.append(res)
        done.add(r.article_id)
        if i % 500 == 0:
            flush(buf, shard_year); buf = []
            save_state(done)
            rate = i / (time.time() - t0)
            eta = (len(todo) - i) / rate / 60
            print(f"  {i}/{len(todo)}  {rate:.1f} art/s  ETA {eta:.0f} min", flush=True)

    flush(buf, shard_year)
    save_state(done)
    print(f"Listo. {len(todo)} procesados en {(time.time()-t0)/60:.1f} min → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
