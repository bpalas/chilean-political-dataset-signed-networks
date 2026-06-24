"""Fetch + combina los N batches del top-up → relations_gemini_topup.parquet.

Descarga cada batch de batch_names_topup.json, aplica el gate de evidencia (cita en body)
con los bodies de la muestra top-up, y concatena todo.

Uso: python scripts/fetch_topup.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GEN = ROOT / "data/processed/re_gemini"
KEYS = ("from_entity", "to_entity", "act_type", "polarity", "issue", "evidence_quote")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import pandas as pd
    from text2sg.batch_gemini import fetch, make_client

    names = json.loads((GEN / "batch_names_topup.json").read_text(encoding="utf-8"))
    samp = pd.read_parquet(ROOT / "data/processed/samples/political_topup_251k.parquet",
                           columns=["article_id", "body"])
    body_of = dict(zip(samp.article_id, samp.body))

    cl = make_client()
    rows, kept, dropped = [], 0, 0
    for i, name in enumerate(names):
        raw = None
        for attempt in range(4):  # descargas de 685MB a veces cortan; reintentar
            try:
                raw = fetch(cl, name)
                break
            except Exception as e:
                print(f"  batch {i} intento {attempt+1} falló: {type(e).__name__}; reintentando…", flush=True)
        if raw is None:
            print(f"  batch {i}: NO se pudo bajar tras 4 intentos", flush=True)
            continue
        print(f"  batch {i}: {len(raw):,} respuestas", flush=True)
        for aid, text in raw.items():
            try:
                rels = json.loads(text).get("relations", [])
            except Exception:
                continue
            body = body_of.get(aid, "")
            for r in rels:
                q = (r.get("evidence_quote") or "").strip()
                if len(q) >= 8 and q in body:
                    rows.append({"article_id": aid, **{k: r.get(k) for k in KEYS}})
                    kept += 1
                else:
                    dropped += 1

    out = GEN / "relations_gemini_topup.parquet"
    pd.DataFrame(rows).to_parquet(out, index=False)
    print(f"\nfetch top-up: {kept:,} relaciones (gate evidencia) | descartadas {dropped:,} → {out}")


if __name__ == "__main__":
    main()
