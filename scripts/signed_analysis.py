"""Red signada — deriva el signo de arista (act_type → {-1,0,+1}), lo agrega a la DB,
y hace análisis de comunidades signadas + balance estructural.

DOS representaciones del signo (estándar en redes signadas):
  - ARISTA: categórico {-1, 0, +1}  (columna `sign`, determinista desde act_type)
  - DÍADA:  continuo [-1, 1]         (media del signo entre dos actores → peso signado)

El signo se deriva DATA-DRIVEN: para cada act_type, su clase de polaridad dominante
(≥60%). Así `calls_on` (57% neutral, la categoría #1) cae a 0 y deja de ensuciar el signo;
`attacks`→-1, `endorses`→+1. Determinista y reproducible.

Comunidades: Louvain sobre el subgrafo de ALIADOS (díadas de peso +). Balance estructural:
qué fracción del peso negativo cae ENTRE comunidades (red balanceada) vs DENTRO (frustración).

Uso: python scripts/signed_analysis.py [--add-column]   (--add-column escribe `sign` en la DB)
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"

GENERICS = {"ejecutivo", "presidente", "estado", "estado de chile", "oposición", "oficialismo",
            "mandatario", "acuerdo", "chile", "plebiscito", "apruebo", "presidente de la república",
            "gobierno", "parlamento", "congreso nacional"}


def derive_sign_map(con) -> dict[str, int]:
    """act_type → {-1,0,+1} por polaridad dominante (≥60%)."""
    rows = con.execute("""
        SELECT act_type,
          1.0*sum(CASE WHEN polarity='positive' THEN 1 ELSE 0 END)/count(*) p,
          1.0*sum(CASE WHEN polarity='negative' THEN 1 ELSE 0 END)/count(*) n
        FROM edges GROUP BY act_type""").fetchall()
    m = {}
    for at, p, n in rows:
        m[at] = 1 if p >= 0.60 else (-1 if n >= 0.60 else 0)
    return m


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-column", action="store_true", help="escribe la columna `sign` en edges")
    args = ap.parse_args()

    import duckdb
    import networkx as nx

    con = duckdb.connect(str(DB))
    con.execute("SET enable_progress_bar=false")
    smap = derive_sign_map(con)
    pos = sorted(a for a, s in smap.items() if s == 1)
    neg = sorted(a for a, s in smap.items() if s == -1)
    print("=== MAPA act_type → signo (data-driven, dominante ≥60%) ===")
    print(f"  +1 ({len(pos)}): {', '.join(pos[:12])}")
    print(f"  -1 ({len(neg)}): {', '.join(neg[:12])}")
    print(f"   0 (neutral): calls_on, negotiates_with, meets_with, … (incluye la categoría #1)\n")

    # ── agregar columna sign (opcional) ──
    if args.add_column:
        case = " ".join(f"WHEN act_type='{a}' THEN {s}" for a, s in smap.items())
        con.execute("ALTER TABLE edges DROP COLUMN IF EXISTS sign")
        con.execute("ALTER TABLE edges ADD COLUMN sign TINYINT")
        con.execute(f"UPDATE edges SET sign = CASE {case} ELSE 0 END")
        dist = con.execute("SELECT sign, count(*) FROM edges GROUP BY sign ORDER BY sign").fetchall()
        print(f"✓ columna `sign` agregada a edges. Distribución: {dict(dist)}\n")

    sign_sql = "CASE " + " ".join(f"WHEN act_type='{a}' THEN {s}" for a, s in smap.items()) + " ELSE 0 END"

    # ── díadas con peso signado continuo [-1,1] ──
    top = con.execute(
        "SELECT node_id, canonical FROM nodes WHERE lower(canonical) NOT IN "
        f"({','.join('?' * len(GENERICS))}) ORDER BY degree DESC LIMIT 110", list(GENERICS)).fetchall()
    keep = {nid for nid, _ in top}
    name = {nid: c for nid, c in top}
    agg = defaultdict(lambda: [0, 0])  # (sumsign, n_valenced)
    for f, t, s in con.execute(f"SELECT from_node_id, to_node_id, {sign_sql} FROM edges").fetchall():
        if f in keep and t in keep and s != 0:
            k = tuple(sorted((f, t)))
            agg[k][0] += s
            agg[k][1] += 1

    dyads = []  # (u, v, w, m)
    for (u, v), (ssum, m) in agg.items():
        if m >= 3:  # estabilidad: ≥3 aristas valenciadas
            dyads.append((u, v, ssum / m, m))
    print(f"=== DÍADAS signadas (top-110 actores, ≥3 aristas valenciadas) ===")
    print(f"  total díadas: {len(dyads)} | peso continuo en [-1, 1]")
    pos_d = [d for d in dyads if d[2] > 0.15]
    neg_d = [d for d in dyads if d[2] < -0.15]
    print(f"  aliadas (w>0.15): {len(pos_d)} | antagónicas (w<-0.15): {len(neg_d)}\n")

    # ── comunidades sobre el grafo de ALIADOS ──
    G = nx.Graph()
    G.add_nodes_from(keep)
    for u, v, w, m in dyads:
        if w > 0.15:
            G.add_edge(u, v, weight=w * m)
    comms = [c for c in nx.community.louvain_communities(G, weight="weight", seed=42) if len(c) >= 4]
    comms.sort(key=len, reverse=True)
    node2comm = {n: i for i, c in enumerate(comms) for n in c}
    print(f"=== COMUNIDADES SIGNADAS (Louvain sobre aliados) — {len(comms)} bloques ===")
    for i, c in enumerate(comms[:6]):
        members = sorted((name[n] for n in c), key=str.lower)
        print(f"\n  Bloque {i+1} (n={len(c)}):")
        print("    " + ", ".join(m[:22] for m in members[:13]))

    # ── balance estructural: ¿los negativos van ENTRE bloques? ──
    within_neg = between_neg = within_pos = between_pos = 0
    for u, v, w, m in dyads:
        ci, cj = node2comm.get(u), node2comm.get(v)
        if ci is None or cj is None:
            continue
        same = ci == cj
        if w < 0:
            within_neg += abs(w) if same else 0
            between_neg += abs(w) if not same else 0
        elif w > 0:
            within_pos += w if same else 0
            between_pos += w if not same else 0
    tot_neg = within_neg + between_neg
    tot_pos = within_pos + between_pos
    print("\n" + "=" * 60)
    print("BALANCE ESTRUCTURAL (teoría: amigos juntos, enemigos separados)")
    print("=" * 60)
    print(f"  peso POSITIVO dentro de bloques : {100*within_pos/tot_pos:4.0f}%  (alto = bien)")
    print(f"  peso NEGATIVO entre  bloques    : {100*between_neg/tot_neg:4.0f}%  (alto = bien)")
    print(f"  → frustración (neg dentro): {100*within_neg/tot_neg:.0f}% | (+ dentro / − entre = red balanceada)")
    con.close()


if __name__ == "__main__":
    main()
