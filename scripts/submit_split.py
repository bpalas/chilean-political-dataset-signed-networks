"""Parte un JSONL grande y submitea N batches (el Files API de Gemini tope ~2GB/archivo).

Streaming (no carga el archivo a RAM). Guarda los batch names en batch_names_topup.json
para pollear/fetchear cada uno y reensamblar.

Uso: python scripts/submit_split.py --parts 2 --genome text2sg/prompts/gemini_champion_v2.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GEN = ROOT / "data/processed/re_gemini"
JSONL = GEN / "input.jsonl"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=int, default=2)
    ap.add_argument("--genome", default=str(ROOT / "text2sg/prompts/gemini_champion_v2.json"))
    args = ap.parse_args()

    from text2sg.batch_gemini import load_genome, make_client, submit

    n = sum(1 for _ in open(JSONL, encoding="utf-8"))
    per = -(-n // args.parts)  # ceil
    print(f"{n:,} requests → {args.parts} partes de ~{per:,}", flush=True)

    # split streaming
    part_paths = []
    fout = None
    idx = -1
    with open(JSONL, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i % per == 0:
                if fout:
                    fout.close()
                idx += 1
                p = GEN / f"input_part{idx}.jsonl"
                part_paths.append(p)
                fout = open(p, "w", encoding="utf-8")
            fout.write(line)
    if fout:
        fout.close()
    for p in part_paths:
        mb = p.stat().st_size / 1e6
        print(f"  {p.name}: {mb:.0f} MB", flush=True)

    genome = load_genome(args.genome)
    cl = make_client()
    names = []
    for i, p in enumerate(part_paths):
        name = submit(cl, p, genome, display=f"re-topup-{i}")
        names.append(name)
        print(f"  ✓ parte {i} → {name}", flush=True)

    (GEN / "batch_names_topup.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(names)} batches creados → {GEN/'batch_names_topup.json'}")


if __name__ == "__main__":
    main()
