"""Experimento de optimización NER — prueba fp16 / autocast / compile y VERIFICA
que las entidades extraídas no cambien (precision-first: un cambio numérico no puede
alterar el grafo).

Compara contra el baseline fp32 actual:
  - velocidad (art/s)
  - paridad de entidades (Jaccard sobre el set (text.lower, type) por artículo)

Uso: python scripts/profile_ner_opt.py --limit 200
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data/processed/samples/political_2019_2022_80k.parquet"


def ent_set(res: dict) -> set:
    return {(e["text"].lower(), e["type"]) for e in res["entities"]}


def parity(a: list[dict], b: list[dict]) -> tuple[float, int, int]:
    """Jaccard medio entre dos corridas + #entidades perdidas/ganadas."""
    jacc, lost, gained = [], 0, 0
    for ra, rb in zip(a, b):
        sa, sb = ent_set(ra), ent_set(rb)
        inter = len(sa & sb)
        union = len(sa | sb) or 1
        jacc.append(inter / union)
        lost += len(sa - sb)
        gained += len(sb - sa)
    return sum(jacc) / len(jacc), lost, gained


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--bs", type=int, default=16)
    args = ap.parse_args()

    import pandas as pd
    import torch
    from text2sg.ner_gliner import extract_batch, load_model

    df = pd.read_parquet(SOURCE, columns=["article_id", "body"]).head(args.limit)
    rows = list(df.itertuples(index=False, name=None))
    print(f"Artículos: {len(rows)} | GPU: {torch.cuda.get_device_name(0)} | bs={args.bs}")

    def run_all(model, autocast_dtype=None) -> tuple[list[dict], float]:
        out: list[dict] = []
        t0 = time.time()
        for start in range(0, len(rows), args.bs):
            batch = rows[start:start + args.bs]
            if autocast_dtype is not None:
                with torch.autocast("cuda", dtype=autocast_dtype):
                    out.extend(extract_batch(model, batch))
            else:
                out.extend(extract_batch(model, batch))
        torch.cuda.synchronize()
        return out, time.time() - t0

    # --- Baseline fp32 ---
    model = load_model()
    run_all(model)  # warmup
    base, t_base = run_all(model)
    r_base = len(rows) / t_base
    print(f"\nbaseline fp32     {t_base:6.2f}s  {r_base:6.1f} art/s")

    # --- autocast fp16 (no toca pesos, casteo on-the-fly) ---
    run_all(model, torch.float16)  # warmup
    a16, t_a16 = run_all(model, torch.float16)
    j, lost, gained = parity(base, a16)
    print(f"autocast fp16     {t_a16:6.2f}s  {len(rows)/t_a16:6.1f} art/s  "
          f"({len(rows)/t_a16/r_base:.2f}x) | Jaccard {j:.4f}  -{lost}/+{gained} ent")

    # --- autocast bf16 (más estable numéricamente que fp16) ---
    run_all(model, torch.bfloat16)
    b16, t_b16 = run_all(model, torch.bfloat16)
    j, lost, gained = parity(base, b16)
    print(f"autocast bf16     {t_b16:6.2f}s  {len(rows)/t_b16:6.1f} art/s  "
          f"({len(rows)/t_b16/r_base:.2f}x) | Jaccard {j:.4f}  -{lost}/+{gained} ent")

    # --- model.half() (pesos en fp16 permanente) ---
    model_h = load_model().half()
    run_all(model_h)
    h16, t_h16 = run_all(model_h)
    j, lost, gained = parity(base, h16)
    print(f"model.half() fp16 {t_h16:6.2f}s  {len(rows)/t_h16:6.1f} art/s  "
          f"({len(rows)/t_h16/r_base:.2f}x) | Jaccard {j:.4f}  -{lost}/+{gained} ent")


if __name__ == "__main__":
    main()
