"""Capa 2 de la curación — genera el set de CANDIDATOS para que Sonnet adjudique.

Tras la Capa 1 (determinista), quedan los merges de juicio: sinónimos sin similitud de
string (Gobierno/Ejecutivo/Estado), siglas no listadas, typos, y mal-etiquetados
("Partido Comunista de China" = ¿el de Chile?). Esto arma lo que Sonnet va a mirar:

  - top_nodes.json   : top-N nodos por grado, con aliases → el núcleo del grafo.
  - candidate_pairs  : pares DENTRO del top-N con token_sort_ratio ≥ thr y MISMO tipo
                       (cross-type bloqueado) → near-duplicates que la Capa 1 no pescó.

Sonnet (Capa 3, workflows/sonnet_curate.workflow.js) lee top_nodes.json y propone merges
del grey-zone; precision-first. Capa 4 (curate_apply.py) aplica.

Uso:
    python scripts/curate_candidates.py --top 150 --threshold 85
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data/processed/graph.duckdb"
CUR_DIR = ROOT / "data/processed/curation"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=150, help="cuántos nodos top-grado")
    ap.add_argument("--threshold", type=int, default=85, help="token_sort_ratio mínimo para par candidato")
    ap.add_argument("--aliases", type=int, default=8, help="aliases por nodo en top_nodes.json")
    args = ap.parse_args()

    import duckdb
    from rapidfuzz import fuzz

    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET enable_progress_bar=false")
    top = con.execute(
        "SELECT node_id, canonical, node_type, degree, n_mentions FROM nodes "
        "ORDER BY degree DESC LIMIT ?", [args.top]).fetchall()

    # aliases (los más frecuentes) por nodo del top
    ids = [t[0] for t in top]
    aliases: dict[str, list] = {i: [] for i in ids}
    rows = con.execute(
        "SELECT node_id, surface_form, n_occurrences FROM aliases "
        "WHERE node_id IN ({}) ORDER BY n_occurrences DESC".format(",".join("?" * len(ids))), ids
    ).fetchall()
    for nid, sf, _ in rows:
        if len(aliases[nid]) < args.aliases:
            aliases[nid].append(sf)
    con.close()

    nodes = [{"node_id": nid, "canonical": c, "type": t, "degree": d, "n_mentions": m,
              "aliases": aliases.get(nid, [])} for nid, c, t, d, m in top]

    # pares candidatos: mismo tipo, token_sort_ratio ≥ thr (cross-type bloqueado)
    pairs = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            if a["type"] != b["type"]:
                continue
            r = int(fuzz.token_sort_ratio(a["canonical"].lower(), b["canonical"].lower()))
            if r >= args.threshold:
                pairs.append({"a": a["node_id"], "b": b["node_id"],
                              "canon_a": a["canonical"], "canon_b": b["canonical"],
                              "type": a["type"], "ratio": r})
    pairs.sort(key=lambda p: -p["ratio"])

    CUR_DIR.mkdir(parents=True, exist_ok=True)
    (CUR_DIR / "top_nodes.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=1), encoding="utf-8")
    (CUR_DIR / "candidate_pairs.json").write_text(
        json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"top_nodes.json: {len(nodes)} nodos (top-{args.top} por grado)")
    print(f"candidate_pairs.json: {len(pairs)} pares (mismo tipo, ratio ≥ {args.threshold})\n")
    print("=== pares candidatos (near-duplicates que la Capa 1 no pescó) ===")
    for p in pairs[:25]:
        print(f"  r={p['ratio']:>3} [{p['type'][:11]:11s}] {p['canon_a'][:30]:30s} ~ {p['canon_b'][:30]}")
    if not pairs:
        print("  (ninguno — la Capa 1 dejó el top sin near-duplicates de string)")
    print(f"\nSiguiente — Capa 3: Workflow({{script:'workflows/sonnet_curate.workflow.js'}}) "
          f"→ curations.json → curate_apply.py")


if __name__ == "__main__":
    main()
