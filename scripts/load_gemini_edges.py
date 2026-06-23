"""Carga las relaciones de Gemini (RE prod) en la tabla `edges` de graph.duckdb.

Actualiza SOLO edges (no toca articles/nodes/mentions → no re-lee shards del NER, que
puede estar corriendo). Linkea entidades crudas del RE a node_id vía el diccionario de
aliases ya resuelto (precision-first: solo edges donde AMBAS entidades resuelven a un
nodo conocido). `node_signed_degree` y `edges_by_period` son vistas → se recalculan solas.

Filtro de calidad: descarta act_types fuera del vocabulario signado (co_occurs no tiene
polaridad → contaminaría una red signada). Configurable con --keep-all.

Uso:
    python scripts/load_gemini_edges.py
    python scripts/load_gemini_edges.py --relations data/processed/re_gemini/relations_gemini.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
D = ROOT / "data/processed"
DB = D / "graph.duckdb"
RUN_ID = "re-gemini-v2"

# Tipos SIN polaridad clara → no son aristas signadas. co_occurs domina (mera co-ocurrencia).
DROP_TYPES = {"co_occurs"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--relations", nargs="+",
                    default=[str(D / "re_gemini/relations_gemini.parquet")],
                    help="una o más parquets de relaciones (se concatenan)")
    ap.add_argument("--keep-all", action="store_true", help="no filtrar act_types (incluye co_occurs)")
    args = ap.parse_args()

    import duckdb
    import pandas as pd
    from text2sg.er import normalize

    con = duckdb.connect(str(DB))

    # 1. diccionario norm(alias) → node_id (de la resolución ya en la DB).
    # `surface_norm` ya viene normalizado por el ER → usarlo directo.
    norm2node: dict[str, str] = {}
    for node_id, snorm in con.execute("SELECT node_id, surface_norm FROM aliases").fetchall():
        if snorm:
            norm2node.setdefault(snorm, node_id)
    # también los canónicos
    for node_id, canon in con.execute("SELECT node_id, canonical FROM nodes").fetchall():
        k = normalize(canon)
        if k:
            norm2node.setdefault(k, node_id)
    print(f"diccionario de linking: {len(norm2node):,} formas → node_id", flush=True)

    # publish_date por artículo (las relaciones no lo traen)
    pub = dict(con.execute("SELECT article_id, publish_date FROM articles").fetchall())
    arts = set(pub)

    # 2. relaciones
    rel = pd.concat([pd.read_parquet(r) for r in args.relations], ignore_index=True)
    n_in = len(rel)
    if not args.keep_all:
        rel = rel[~rel["act_type"].isin(DROP_TYPES)]
    print(f"relaciones: {n_in:,} → {len(rel):,} tras filtro de act_type "
          f"({'sin filtro' if args.keep_all else 'drop ' + ','.join(DROP_TYPES)})", flush=True)

    # 3. linkear entidades → node_id (ambas deben resolver, distintas, art conocido)
    erows = []
    unresolved = 0
    for r in rel.itertuples():
        if r.article_id not in arts:
            continue
        if not isinstance(r.from_entity, str) or not isinstance(r.to_entity, str):
            unresolved += 1
            continue
        fn = norm2node.get(normalize(r.from_entity))
        tn = norm2node.get(normalize(r.to_entity))
        if not fn or not tn:
            unresolved += 1
            continue
        if fn == tn:
            continue
        if r.polarity not in ("positive", "negative", "neutral"):
            unresolved += 1  # sin polaridad válida → inútil en red signada
            continue
        if not isinstance(r.act_type, str) or not r.act_type:
            unresolved += 1  # act_type nulo
            continue
        pdate = pub.get(r.article_id)
        period = str(pdate.year) if pdate is not None else None
        erows.append((fn, tn, r.article_id, RUN_ID, r.act_type, r.polarity,
                      r.issue, r.evidence_quote, None, pdate, period))

    cols = ["from_node_id", "to_node_id", "article_id", "run_id", "act_type", "polarity",
            "issue", "evidence_quote", "confidence", "publish_date", "period"]
    edf = pd.DataFrame(erows, columns=cols)
    edf = edf.drop_duplicates(["from_node_id", "to_node_id", "article_id", "act_type"]).reset_index(drop=True)
    edf.insert(0, "edge_id", range(len(edf)))
    link_rate = 100 * (len(rel) - unresolved) / max(len(rel), 1)
    print(f"linkeadas: {len(edf):,} aristas únicas | sin resolver: {unresolved:,} "
          f"({link_rate:.0f}% de entidades resueltas)", flush=True)

    # 4. registrar el run (trazabilidad) y reemplazar edges en una transacción
    con.execute("BEGIN")
    con.execute("DELETE FROM edges")
    con.execute("DELETE FROM runs WHERE run_id = ?", [RUN_ID])
    con.execute(
        "INSERT INTO runs (run_id, kind, model, genome_id, prompt_id, params, n_items, notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [RUN_ID, "re", "gemini-2.5-flash-lite", "gemini_champion_v2", "gemini_champion_v2",
         '{"batch":true,"max_output_tokens":8192,"evidence_gate":true}', int(len(edf)),
         "RE prod 80k batch flash-lite"])
    con.register("edf", edf)
    con.execute(f"INSERT INTO edges SELECT {','.join(['edge_id'] + cols)} FROM edf")
    con.execute("UPDATE nodes SET degree=(SELECT count(*) FROM edges e "
                "WHERE e.from_node_id=nodes.node_id OR e.to_node_id=nodes.node_id)")
    con.execute("COMMIT")
    print(f"\n✓ edges: {len(edf):,} cargadas (run {RUN_ID}). Vistas signed_degree/by_period recalculadas.", flush=True)

    # 5. sanity: top actores por grado signado
    print("\n=== top 10 grado signado (node_signed_degree) ===", flush=True)
    rows = con.execute(
        "SELECT canonical, pos_degree, neg_degree, degree FROM node_signed_degree "
        "ORDER BY degree DESC LIMIT 10").fetchall()
    for canon, pos, neg, deg in rows:
        print(f"  {canon[:34]:34s} deg {deg:>6}  +{pos} / -{neg}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
