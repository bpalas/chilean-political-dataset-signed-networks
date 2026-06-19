"""Probe de profiling para NER GLiNER — mide DÓNDE se va el tiempo antes de optimizar.

Mide sobre N artículos reales:
  1. Tiempo total y art/s con el camino actual (extract_batch, batch_size=16).
  2. Desglose cProfile (top funciones por tiempo acumulado).
  3. Barrido de batch_size para encontrar el punto óptimo de GPU.
  4. ¿El tokenizer es 'fast' (Rust) o 'slow' (Python)?

Uso: python scripts/profile_ner.py --limit 200
"""
from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    import pandas as pd
    import torch
    from text2sg.ner_gliner import extract_batch, load_model

    df = pd.read_parquet(SOURCE, columns=["article_id", "body"]).head(args.limit)
    rows = list(df.itertuples(index=False, name=None))
    print(f"Artículos: {len(rows)} | GPU: {torch.cuda.get_device_name(0)}")

    model = load_model()

    # ¿Fast tokenizer?
    tok = getattr(model, "data_processor", None)
    tok = getattr(tok, "transformer_tokenizer", None) or getattr(model, "tokenizer", None)
    is_fast = getattr(tok, "is_fast", None)
    print(f"Tokenizer: {type(tok).__name__} | is_fast={is_fast}")

    def run_all(bs: int) -> float:
        t0 = time.time()
        for start in range(0, len(rows), bs):
            extract_batch(model, rows[start:start + bs])
        torch.cuda.synchronize()
        return time.time() - t0

    # Warmup (descarta la primera pasada: carga kernels CUDA)
    run_all(16)

    # 1+3: barrido de batch_size
    print("\n=== Barrido batch_size ===")
    for bs in [8, 16, 32, 48, 64]:
        torch.cuda.reset_peak_memory_stats()
        dt = run_all(bs)
        mem = torch.cuda.max_memory_allocated() / 1e9
        print(f"  bs={bs:3d}  {dt:6.2f}s  {len(rows)/dt:6.1f} art/s  | VRAM pico {mem:.2f} GB")

    # 2: cProfile con bs=16 (el default actual)
    print("\n=== cProfile (bs=16, top 15 por tiempo acumulado) ===")
    pr = cProfile.Profile()
    pr.enable()
    run_all(16)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(15)
    print(s.getvalue())


if __name__ == "__main__":
    main()
