"""Red signada — agrega el signo numérico (de la polaridad de Gemini) y hace análisis
de comunidades signadas + balance estructural.

EL SIGNO ES LA POLARIDAD QUE EXTRAJO GEMINI (no se deriva de act_type — eso fue un rodeo
que daba ~lo mismo). `sign = polarity`:  positive→+1, negative→-1, neutral→0.

DOS representaciones (estándar en redes signadas):
  - ARISTA: categórico {-1, 0, +1}  (columna `sign` = polaridad numérica)
  - DÍADA:  continuo [-1, 1]         (media del signo entre dos actores)

⚠️ NODOS DE ROL TEMPORALES: "Gobierno de Chile", "Oposición", "Oficialismo", "Presidente",
"Ejecutivo" cambian de referente en el cambio de mando (mar 2022, Piñera→Boric). Agregar
sus díadas sobre toda la ventana mezcla dos actores → analizar POR PERÍODO (columna
`period` / vista `edges_by_period`). Actores estables (personas, partidos) agregan bien.

Uso: python scripts/signed_analysis.py [--add-column]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"

# signo numérico = polaridad de Gemini
SIGN_SQL = "CASE polarity WHEN 'positive' THEN 1 WHEN 'negative' THEN -1 ELSE 0 END"

GENERICS = {"ejecutivo", "presidente", "estado", "estado de chile", "oposición", "oficialismo",
            "mandatario", "acuerdo", "chile", "plebiscito", "apruebo", "presidente de la república",
            "gobierno", "parlamento", "congreso nacional", "gobierno de chile"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-column", action="store_true", help="escribe/actualiza la columna `sign`")
    ap.add_argument("--period", default=None, help="filtrar a un período (año), ej. 2021")
    args = ap.parse_args()

    import duckdb
    import networkx as nx

    con = duckdb.connect(str(DB))
    con.execute("SET enable_progress_bar=false")

    # ── (a) columna sign = polaridad numérica ──
    # No usar DROP COLUMN: las vistas (signed_degree/by_period) dependen de `edges`
    # y DuckDB lo bloquea. ADD si falta, luego UPDATE.
    if args.add_column:
        cols = [c[0] for c in con.execute("DESCRIBE edges").fetchall()]
        if "sign" not in cols:
            con.execute("ALTER TABLE edges ADD COLUMN sign TINYINT")
        con.execute(f"UPDATE edges SET sign = {SIGN_SQL}")
        dist = dict(con.execute("SELECT sign, count(*) FROM edges GROUP BY sign ORDER BY sign").fetchall())
        print(f"✓ columna `sign` = polaridad numérica. Distribución: {dist}\n")

    where = f"WHERE period = '{args.period}'" if args.period else ""
    scope = f"período {args.period}" if args.period else "toda la ventana (2014-2026)"
    print(f"=== ANÁLISIS SIGNADO — {scope} ===")
    print("    (nodos de rol como 'Gobierno' se excluyen del clustering por conflación temporal)\n")

    top = con.execute(
        "SELECT node_id, canonical FROM nodes WHERE lower(canonical) NOT IN "
        f"({','.join('?' * len(GENERICS))}) ORDER BY degree DESC LIMIT 110", list(GENERICS)).fetchall()
    keep = {nid for nid, _ in top}
    name = {nid: c for nid, c in top}

    agg = defaultdict(lambda: [0, 0])
    for f, t, s in con.execute(f"SELECT from_node_id, to_node_id, {SIGN_SQL} FROM edges {where}").fetchall():
        if f in keep and t in keep and s != 0:
            k = tuple(sorted((f, t)))
            agg[k][0] += s
            agg[k][1] += 1
    dyads = [(u, v, ss / m, m) for (u, v), (ss, m) in agg.items() if m >= 3]
    print(f"díadas (top-110, ≥3 valenciadas): {len(dyads)} | peso continuo [-1,1]")

    # comunidades sobre aliados (peso +)
    G = nx.Graph()
    G.add_nodes_from(keep)
    for u, v, w, m in dyads:
        if w > 0.15:
            G.add_edge(u, v, weight=w * m)
    comms = sorted([c for c in nx.community.louvain_communities(G, weight="weight", seed=42) if len(c) >= 4],
                   key=len, reverse=True)
    node2comm = {n: i for i, c in enumerate(comms) for n in c}
    print(f"comunidades (Louvain sobre aliados): {len(comms)} bloques\n")
    for i, c in enumerate(comms[:6]):
        members = sorted((name[n] for n in c), key=str.lower)
        print(f"  Bloque {i+1} (n={len(c)}): " + ", ".join(m[:20] for m in members[:11]))

    # balance estructural
    wn = bn = wp = bp = 0.0
    for u, v, w, m in dyads:
        ci, cj = node2comm.get(u), node2comm.get(v)
        if ci is None or cj is None:
            continue
        same = ci == cj
        if w < 0:
            wn += abs(w) if same else 0; bn += abs(w) if not same else 0
        elif w > 0:
            wp += w if same else 0; bp += w if not same else 0
    print("\n  BALANCE ESTRUCTURAL:")
    print(f"    + dentro de bloques: {100*wp/(wp+bp):4.0f}%  |  − entre bloques: {100*bn/(wn+bn):4.0f}%  (altos = balanceada)")
    con.close()


if __name__ == "__main__":
    main()
