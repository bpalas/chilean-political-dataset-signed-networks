"""Pasada 2 (ER) — resuelve los actores de las relaciones extraídas a nodos canónicos.

Lee relations.parquet (RE), tipa cada surface form con el NER GLiNER, construye el
gazetteer de aliases (seed clivaje + proto Haiku) y clusteriza con er_resolve. Reporta
la tasa de colapso y escribe nodes.parquet + edges.parquet (grafo).

Uso: python scripts/run_er.py
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from text2sg.er import normalize  # noqa: E402
from text2sg.er_resolve import build_alias_gazetteer, resolve_mentions  # noqa: E402

RE = ROOT / "data/processed/re/relations.parquet"
OUT = ROOT / "data/processed/er"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rel = pd.read_parquet(RE)

    # Tipo por surface (del NER GLiNER, mayoritario)
    type_by_norm: dict[str, Counter] = {}
    for s in glob.glob(str(ROOT / "data/processed/ner/gliner/year=*/part-*.parquet")):
        for ents in pd.read_parquet(s)["entities"]:
            for e in json.loads(ents):
                type_by_norm.setdefault(normalize(e["text"]), Counter())[e["type"]] += 1
    def typ(surface: str) -> str:
        c = type_by_norm.get(normalize(surface))
        return c.most_common(1)[0][0] if c else "unknown"

    # Menciones (surface, type, freq)
    freq = pd.concat([rel.from_entity, rel.to_entity]).value_counts()
    mentions = [(s, typ(s), int(n)) for s, n in freq.items()]

    # Gazetteer de aliases
    seed = json.loads((ROOT / "data/processed/gazetteer.json").read_text(encoding="utf-8"))
    proto = json.loads((ROOT / "data/processed/ner/proto_gazetteer.json").read_text(encoding="utf-8"))
    proto = proto.get("gazetteer", proto)
    gz = build_alias_gazetteer(seed, proto)

    assign, nodes = resolve_mentions(mentions, gz)

    # --- Reporte ---
    print(f"=== ER sobre {len(rel)} relaciones ===")
    print(f"surface forms únicos : {len(mentions)}")
    print(f"nodos canónicos      : {len(nodes)}")
    print(f"tasa de colapso      : {len(mentions)/max(1,len(nodes)):.2f}x  "
          f"({len(mentions)-len(nodes)} duplicados unificados)")
    multi = sorted([n for n in nodes if len(n["aliases"]) > 1], key=lambda n: -n["n"])
    print(f"\n=== Top nodos que colapsaron varias formas ===")
    for n in multi[:10]:
        print(f"  [{n['type'][:6]:6s}] {n['canonical'][:28]:28s} ← {n['aliases'][:4]}")

    # --- Grafo: edges con node_ids + nodes ---
    rel = rel.copy()
    rel["from_node"] = rel.from_entity.map(assign)
    rel["to_node"] = rel.to_entity.map(assign)
    rel = rel[rel.from_node != rel.to_node]  # sin self-loops tras resolver
    rel.to_parquet(OUT / "edges.parquet", index=False)
    pd.DataFrame([{**n, "aliases": json.dumps(n["aliases"], ensure_ascii=False)} for n in nodes]) \
        .to_parquet(OUT / "nodes.parquet", index=False)
    print(f"\nnodos: {len(nodes)} → {OUT/'nodes.parquet'}")
    print(f"aristas: {len(rel)} (tras quitar self-loops) → {OUT/'edges.parquet'}")


if __name__ == "__main__":
    main()
