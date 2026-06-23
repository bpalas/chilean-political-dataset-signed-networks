"""ER a escala sobre la UNIÓN de muestras — normaliza los nodos de toda la ventana.

Lee las menciones del NER (shards GLiNER) de los artículos que están en las muestras dadas,
agrega (surface, tipo mayoritario, freq), clusteriza con er_resolve (blocking por token +
guardas) y escribe una resolución unificada {assign, nodes} para alimentar el RE.

A diferencia de run_er.py (que resuelve desde las relaciones del RE), este resuelve desde
las MENCIONES del NER → es el espacio de nodos PREVIO al RE (lo que el RE recibe como
given_entities normalizados).

Uso:
    python scripts/er_scale.py --samples political_2019_2022_80k political_2022_2026_80k \
        --out data/processed/er/resolution_union.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

D = ROOT / "data/processed"
from text2sg.er import normalize  # noqa: E402
from text2sg.er_resolve import build_alias_gazetteer, resolve_mentions  # noqa: E402

ACTOR_TYPES = {"person", "party", "institution", "coalition", "movement", "org"}


def main() -> None:
    import pandas as pd
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="+", required=True,
                    help="nombres de parquets en samples/ (sin .parquet)")
    ap.add_argument("--out", default=str(D / "er/resolution_union.json"))
    args = ap.parse_args()

    # article_ids de la unión de muestras
    want = set()
    for s in args.samples:
        ids = pd.read_parquet(D / f"samples/{s}.parquet", columns=["article_id"])["article_id"]
        want |= set(ids)
        print(f"  {s}: {len(ids):,} artículos", flush=True)
    print(f"unión: {len(want):,} artículos", flush=True)

    # agregar menciones del NER (solo de esos artículos)
    surf_type: dict[str, Counter] = {}
    surf_freq: Counter = Counter()
    n_shards = 0
    for sh in glob.glob(str(D / "ner/gliner/year=*/part-*.parquet")):
        try:
            df = pd.read_parquet(sh, columns=["article_id", "entities"])
        except Exception:
            continue
        n_shards += 1
        for aid, ents in zip(df.article_id, df.entities):
            if aid not in want:
                continue
            for e in json.loads(ents):
                if e["type"] in ACTOR_TYPES:
                    surf_type.setdefault(e["text"], Counter())[e["type"]] += 1
                    surf_freq[e["text"]] += 1
    print(f"shards leídos: {n_shards} | surface forms (actores): {len(surf_freq):,}", flush=True)

    mentions = [(s, surf_type[s].most_common(1)[0][0], int(f)) for s, f in surf_freq.items()]

    # gazetteer de aliases (seed clivaje + proto Haiku)
    seed = json.loads((D / "gazetteer.json").read_text(encoding="utf-8"))
    proto = json.loads((D / "ner/proto_gazetteer.json").read_text(encoding="utf-8"))
    proto = proto.get("gazetteer", proto)
    gz = build_alias_gazetteer(seed, proto)

    assign, nodes = resolve_mentions(mentions, gz)
    print(f"→ {len(mentions):,} surface forms → {len(nodes):,} nodos "
          f"({len(mentions)/max(1,len(nodes)):.2f}x colapso)", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"assign": assign, "nodes": nodes}, ensure_ascii=False), encoding="utf-8")
    print(f"✓ resolución → {out}", flush=True)


if __name__ == "__main__":
    main()
