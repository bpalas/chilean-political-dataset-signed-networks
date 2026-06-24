"""Exporta una versión PÚBLICA y copyright-safe de la red signada.

Las noticias son CC-BY-NC (copyright) → NO se suben body, title, ni evidence_quote.
Sí se suben: el grafo (nodos + aristas signadas), article_id (para joinear con el corpus
licenciado), fechas/período/fuente. Todo lo que es metadata extraída, no texto de noticia.

Salida: data/processed/public_network/ (nodes, edges, articles_meta + stats.json)

Uso: python scripts/export_public_network.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"
OUT = ROOT / "data/processed/public_network"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import duckdb
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET enable_progress_bar=false")

    # nodes: actores + grado signado (sin texto)
    con.execute(f"""COPY (
        SELECT n.node_id, n.canonical, n.node_type,
               COALESCE(sd.degree,0) AS degree,
               COALESCE(sd.pos_degree,0) AS pos_degree,
               COALESCE(sd.neg_degree,0) AS neg_degree,
               n.n_mentions, n.curated
        FROM nodes n LEFT JOIN node_signed_degree sd USING (node_id)
        WHERE COALESCE(sd.degree,0) > 0
        ORDER BY degree DESC
    ) TO '{(OUT/'nodes.parquet').as_posix()}' (FORMAT parquet)""")

    # edges: relaciones signadas SIN evidence_quote (texto de noticia)
    con.execute(f"""COPY (
        SELECT from_node_id, to_node_id, article_id, act_type, polarity, sign,
               issue, publish_date, period
        FROM edges
    ) TO '{(OUT/'edges.parquet').as_posix()}' (FORMAT parquet)""")

    # articles_meta: SOLO metadata (sin title ni body)
    con.execute(f"""COPY (
        SELECT article_id, source, publish_date, year, period
        FROM articles
    ) TO '{(OUT/'articles_meta.parquet').as_posix()}' (FORMAT parquet)""")

    # stats para el README
    s = {}
    s["n_articles"] = con.execute("SELECT count(*) FROM articles").fetchone()[0]
    s["n_nodes"] = con.execute("SELECT count(*) FROM nodes WHERE degree>0").fetchone()[0]
    s["n_edges"] = con.execute("SELECT count(*) FROM edges").fetchone()[0]
    s["polarity"] = dict(con.execute("SELECT polarity, count(*) FROM edges GROUP BY 1").fetchall())
    s["node_types"] = dict(con.execute(
        "SELECT node_type, count(*) FROM nodes WHERE degree>0 GROUP BY 1 ORDER BY 2 DESC").fetchall())
    s["year_range"] = con.execute("SELECT min(year), max(year) FROM articles").fetchone()
    s["top_actors"] = con.execute(
        "SELECT canonical, degree, pos_degree, neg_degree FROM node_signed_degree "
        "ORDER BY degree DESC LIMIT 15").fetchall()
    (OUT / "stats.json").write_text(json.dumps(s, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    con.close()

    for f in ("nodes", "edges", "articles_meta"):
        p = OUT / f"{f}.parquet"
        print(f"  {f}.parquet: {p.stat().st_size/1e6:.0f} MB")
    print(f"\nstats: {s['n_articles']:,} art | {s['n_nodes']:,} nodos | {s['n_edges']:,} aristas")
    print(f"polarity: {s['polarity']}")


if __name__ == "__main__":
    main()
