"""Materializa node_signed_degree como TABLA (no vista) — rápido a escala.

La vista hacía un join `IN (from,to)` O(edges×nodos) que a >1M aristas se cuelga.
Esta versión agrega con UNION ALL de from/to → segundos. Re-correr tras cambiar edges.

Uso: python scripts/materialize_signed_degree.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import duckdb
    con = duckdb.connect(str(DB))
    con.execute("SET enable_progress_bar=false")
    con.execute("DROP VIEW IF EXISTS node_signed_degree")
    con.execute("""
        CREATE OR REPLACE TABLE node_signed_degree AS
        SELECT n.node_id, n.canonical, n.node_type,
               COALESCE(d.pos, 0) AS pos_degree,
               COALESCE(d.neg, 0) AS neg_degree,
               COALESCE(d.deg, 0) AS degree
        FROM nodes n
        LEFT JOIN (
            SELECT nid, count(*) AS deg,
                   sum(CASE WHEN pol = 'positive' THEN 1 ELSE 0 END) AS pos,
                   sum(CASE WHEN pol = 'negative' THEN 1 ELSE 0 END) AS neg
            FROM (SELECT from_node_id AS nid, polarity AS pol FROM edges
                  UNION ALL SELECT to_node_id, polarity FROM edges)
            GROUP BY nid
        ) d ON n.node_id = d.nid
    """)
    n = con.execute("SELECT count(*) FROM node_signed_degree").fetchone()[0]
    print(f"✓ node_signed_degree materializada ({n:,} nodos)")
    print("top 8 grado signado:")
    for c, p, ng, dg in con.execute(
            "SELECT canonical,pos_degree,neg_degree,degree FROM node_signed_degree "
            "ORDER BY degree DESC LIMIT 8").fetchall():
        print(f"  {dg:>7,}  {c[:34]:34s} +{p}/-{ng}")
    con.close()


if __name__ == "__main__":
    main()
