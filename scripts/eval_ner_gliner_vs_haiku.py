"""F3 — head-to-head NER: GLiNER (dedicado, local) vs Haiku (baseline del piloto).

Corre GLiNER sobre los mismos artículos del piloto Haiku (gold v2) y compara cobertura,
tipos y solapamiento. Cierra la decisión F3 (modelo NER de producción) con datos.

Uso: python scripts/eval_ner_gliner_vs_haiku.py
Salida: data/processed/ner/gliner_raw_60art.json + reporte por stdout.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from text2sg.ner_gliner import run  # noqa: E402

HAIKU = ROOT / "data/processed/ner/ner_raw_60art.json"
ARTS = ROOT / "data/gold/synthetic_v2/articles.parquet"
OUT = ROOT / "data/processed/ner/gliner_raw_60art.json"


def norm(s: str) -> str:
    return s.strip().lower()


def main() -> None:
    haiku = json.loads(HAIKU.read_text(encoding="utf-8"))
    pilot_ids = [a["article_id"] for a in haiku]
    arts = pd.read_parquet(ARTS)
    df = arts[arts["article_id"].isin(pilot_ids)][["article_id", "body"]].reset_index(drop=True)
    print(f"Corriendo GLiNER sobre {len(df)} artículos del piloto...", flush=True)

    gliner = run(df)
    OUT.write_text(json.dumps(gliner, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- métricas GLiNER ---
    g_per = [len(a["entities"]) for a in gliner]
    g_all = [e for a in gliner for e in a["entities"]]
    g_types = Counter(e["type"] for e in g_all)
    g_canon = {norm(e["text"]) for e in g_all}

    # --- métricas Haiku (baseline) ---
    h_per = [len(a["entities"]) for a in haiku]
    h_all = [e for a in haiku for e in a["entities"]]
    h_types = Counter(e["type"] for e in h_all)
    h_canon = {norm(e["canonical"]) for e in h_all}

    overlap = g_canon & h_canon

    def line(label, gv, hv):
        print(f"  {label:24s} GLiNER {str(gv):>8s}   Haiku {str(hv):>8s}")

    print("\n=== Head-to-head (mismos {} artículos) ===".format(len(df)))
    line("entidades totales", len(g_all), len(h_all))
    line("entidades/artículo (media)", f"{len(g_all)/len(gliner):.1f}", f"{len(h_all)/len(haiku):.1f}")
    line("artículos sin entidades", sum(1 for n in g_per if n == 0), sum(1 for n in h_per if n == 0))
    line("canonicals únicos", len(g_canon), len(h_canon))

    print("\n=== Distribución de tipos ===")
    all_types = sorted(set(g_types) | set(h_types), key=lambda t: -(g_types[t] + h_types[t]))
    for t in all_types:
        print(f"  {t:14s} GLiNER {g_types[t]:4d}   Haiku {h_types[t]:4d}")

    print("\n=== Solapamiento de entidades (canonical normalizado) ===")
    print(f"  GLiNER ∩ Haiku : {len(overlap)}")
    print(f"  solo GLiNER    : {len(g_canon - h_canon)}")
    print(f"  solo Haiku     : {len(h_canon - g_canon)}")
    print(f"\nGuardado: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
