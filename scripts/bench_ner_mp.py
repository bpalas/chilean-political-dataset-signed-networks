"""Benchmark de throughput AGREGADO: N workers × fp16 sobre la GPU.

Responde la pregunta de producción: ¿cuántos workers saturan la RTX 4070 y qué
art/s agregado da con --fp16? Cada worker carga el modelo y procesa su slice;
se mide wall-clock total → art/s reales (no per-proceso).

Uso: python scripts/bench_ner_mp.py --per-worker 120
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"


def _worker(rows, fp16, q):
    try:
        import torch
        from text2sg.ner_gliner import extract_batch, load_model
        model = load_model()
        # warmup (carga kernels) — no se cronometra
        extract_batch(model, rows[:8], fp16=fp16)
        torch.cuda.synchronize()
        t0 = time.time()
        for start in range(0, len(rows), 16):
            extract_batch(model, rows[start:start + 16], fp16=fp16)
        torch.cuda.synchronize()
        q.put((len(rows), time.time() - t0, torch.cuda.max_memory_allocated() / 1e9))
    except Exception as e:  # un worker que muere (p.ej. OOM) reporta error en vez de colgar al padre
        q.put(("ERR", repr(e)[:80], 0.0))


def bench(rows_all, nw, fp16, ctx):
    slices = [rows_all[i::nw] for i in range(nw)]
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(slices[i], fp16, q)) for i in range(nw)]
    t0 = time.time()
    for p in procs:
        p.start()
    res = []
    for _ in procs:
        try:
            res.append(q.get(timeout=300))
        except Exception:
            res.append(("ERR", "timeout", 0.0))
    for p in procs:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()
    errs = [r for r in res if r[0] == "ERR"]
    if errs:
        return None, errs[0][1], 0.0, 0.0, 0.0
    total_art = sum(r[0] for r in res)
    compute_t = max(r[1] for r in res)  # throughput agregado = art / max tiempo de cómputo
    vram = sum(r[2] for r in res)
    return total_art, compute_t, total_art / compute_t, vram, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-worker", type=int, default=120)
    ap.add_argument("--workers", default="1,2,3")
    args = ap.parse_args()

    import pandas as pd
    ctx = mp.get_context("spawn")
    worker_counts = [int(x) for x in args.workers.split(",")]
    maxn = max(worker_counts) * args.per_worker
    df = pd.read_parquet(SOURCE, columns=["article_id", "body"]).head(maxn)
    rows_all = list(df.itertuples(index=False, name=None))
    print(f"GPU sat test | {args.per_worker} art/worker\n", flush=True)
    print(f"{'workers':>7} {'fp16':>5} {'art':>5} {'comp_s':>7} {'art/s':>7} {'VRAM_GB':>8}", flush=True)
    for fp16 in (False, True):
        for nw in worker_counts:
            rows = rows_all[: nw * args.per_worker]
            tot, ct, rate, vram, wall = bench(rows, nw, fp16, ctx)
            if tot is None:
                print(f"{nw:>7} {str(fp16):>5}   ERR: {ct}", flush=True)
            else:
                print(f"{nw:>7} {str(fp16):>5} {tot:>5} {ct:>7.2f} {rate:>7.1f} {vram:>8.2f}", flush=True)


if __name__ == "__main__":
    main()
