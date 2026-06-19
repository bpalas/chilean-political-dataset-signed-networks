"""Pasada 1 a escala — GLiNER NER con multiprocessing (GPU compartida).

El cuello de GLiNER es la tokenización en CPU (single-thread), no la GPU (que queda
~35x sobrada). Por eso paralelizamos en CPU: N workers tokenizan en paralelo y alimentan
la misma GPU. Cada worker carga el modelo una vez, procesa su slice de artículos y
escribe SUS PROPIOS shards (`part-w{wid}-*.parquet`) y state (`state-w{wid}.json`) →
sin locks ni races. Resume: al reiniciar se unen todos los state-w*.json y se omiten.

Reusable en todas las escalas vía --source:
    HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner.py --workers 4            # 80k (default)
    HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner.py --source <383k.parquet> --workers 6
    HF_HUB_DISABLE_SYMLINKS=1 python scripts/run_ner_gliner.py --limit 500 --workers 3 # smoke

Salida: data/processed/ner/gliner/year=YYYY/part-w{wid}-NNNN.parquet  +  state-w*.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_SOURCE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"
OUT = ROOT / "data/processed/ner/gliner"
SHARD_SIZE = 2000


def _done_ids() -> set[str]:
    """Une todos los state-*.json existentes → article_ids ya procesados (capta el
    prefijo de shard 's{k}-' cuando se reparte entre máquinas)."""
    done: set[str] = set()
    for sf in OUT.glob("state-*.json"):
        done |= set(json.loads(sf.read_text(encoding="utf-8")))
    return done


def worker(wid: int, source: str, ids: list[str], threshold: float,
           batch_size: int, shard_tag: str = "", fp16: bool = False) -> None:
    """Procesa un slice de article_ids. Escribe shards + state propios. `shard_tag`
    ('s0-', 's1-'…) separa el output entre máquinas para que no colisione al consolidar."""
    import pandas as pd  # import dentro del worker (spawn)
    from text2sg.ner_gliner import extract_batch, load_model

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    want = set(ids)
    df = pd.read_parquet(source, columns=["article_id", "body", "year"])
    df = df[df["article_id"].isin(want)].sort_values("year").reset_index(drop=True)
    rows = list(df.itertuples(index=False, name=None))
    if not rows:
        return

    model = load_model()
    state_path = OUT / f"state-{shard_tag}w{wid}.json"
    done: set[str] = set(json.loads(state_path.read_text(encoding="utf-8"))) if state_path.exists() else set()
    buf: list[dict] = []
    shard_year = None
    part = 0
    t0 = time.time()
    n = 0
    last_save = 0

    def flush() -> None:
        nonlocal part, buf
        if not buf:
            return
        ydir = OUT / f"year={shard_year}"
        ydir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"article_id": r["article_id"],
                       "entities": json.dumps(r["entities"], ensure_ascii=False)}
                      for r in buf]).to_parquet(ydir / f"part-{shard_tag}w{wid}-{part:05d}.parquet", index=False)
        part += 1
        buf = []

    for start in range(0, len(rows), batch_size):
        chunk = [(aid, body, yr) for aid, body, yr in rows[start : start + batch_size]]
        results = extract_batch(model, [(aid, body) for aid, body, _ in chunk],
                                threshold=threshold, fp16=fp16)
        for (aid, _b, yr), res in zip(chunk, results):
            if shard_year is not None and (yr != shard_year or len(buf) >= SHARD_SIZE):
                flush()
            shard_year = yr
            buf.append(res)
            done.add(aid)
            n += 1
        if n - last_save >= 500:
            flush()
            state_path.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
            last_save = n
            rate = n / (time.time() - t0)
            print(f"  [w{wid}] {n}/{len(rows)}  {rate:.1f} art/s", flush=True)

    flush()
    state_path.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    print(f"  [w{wid}] done {len(rows)} en {(time.time()-t0)/60:.1f} min", flush=True)


def main() -> None:
    import pandas as pd
    import multiprocessing as mp

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--fp16", action="store_true",
                    help="inferencia half precision (1.6x, paridad de entidades ~0.99 vs fp32)")
    ap.add_argument("--shard", default=None,
                    help="k/N: esta máquina procesa la fracción k de N (ej. 0/2 y 1/2 en 2 laptops)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.source, columns=["article_id", "year"]).sort_values("year")
    if args.limit:
        df = df.head(args.limit)
    done = _done_ids()
    todo = [a for a in df["article_id"].tolist() if a not in done]

    # Sharding entre máquinas: k/N → esta máquina toma 1 de cada N artículos (fracción k).
    shard_tag = ""
    if args.shard:
        k, nshard = (int(x) for x in args.shard.split("/"))
        todo = [a for i, a in enumerate(todo) if i % nshard == k]
        shard_tag = f"s{k}-"

    print(f"Source {Path(args.source).name} | total {len(df)} | hechos {len(done)} | "
          f"shard {args.shard or 'todo'} → pendientes {len(todo)} | workers {args.workers}", flush=True)
    if not todo:
        print("Nada que hacer.")
        return

    # Reparto contiguo (el df viene ordenado por año → cada worker tiende a años homogéneos)
    nw = max(1, args.workers)
    slices = [todo[i::nw] for i in range(nw)]  # round-robin: balancea carga por longitud
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=worker, args=(i, args.source, slices[i], args.threshold, args.batch_size, shard_tag, args.fp16))
             for i in range(nw) if slices[i]]
    t0 = time.time()
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    print(f"Listo. {len(todo)} artículos en {(time.time()-t0)/60:.1f} min → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
