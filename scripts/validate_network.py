"""Validación de cara (face validity) de la red signada — ¿reproduce la política real?

Tres chequeos contra hechos conocidos del Chile 2019-2022. $0, local. NO valida edges
individuales (eso es el gold f0.5) sino la ESTRUCTURA agregada — el test que decide si la
red sirve para análisis.

  1. Comunidades vs coaliciones — Louvain sobre el subgrafo de aliados (aristas netas +)
     de los top actores. ¿Los clusters reproducen derecha / Apruebo Dignidad / ex-Concertación?
  2. Signo por díadas conocidas — ¿Gobierno↔oposición neto negativo? ¿intra-coalición +?
  3. Polarización temporal — % de aristas negativas por mes. ¿Picos en estallido (10/2019),
     plebiscito (10/2020), rechazo (09/2022)?

Uso: python scripts/validate_network.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"

GENERICS = {"ejecutivo", "presidente", "estado", "estado de chile", "oposición", "oficialismo",
            "mandatario", "acuerdo", "chile", "plebiscito", "apruebo", "presidente de la república",
            "gobierno", "parlamento", "congreso nacional"}

# Bloques conocidos (canonical en minúscula) para evaluar las comunidades detectadas.
BLOCS = {
    "DERECHA": {"sebastián piñera", "josé antonio kast", "unión demócrata independiente",
                "renovación nacional", "evópoli", "sebastián sichel", "evelyn matthei",
                "mario desbordes", "ignacio briones", "joaquín lavín", "manuel josé ossandón",
                "partido republicano", "chile vamos", "andrés allamand", "víctor pérez"},
    "APRUEBO_DIGNIDAD": {"gabriel boric font", "daniel jadue", "camila vallejo", "frente amplio",
                         "partido comunista de chile", "revolución democrática", "convergencia social",
                         "apruebo dignidad", "izkia siches", "giorgio jackson"},
    "EX_CONCERTACION": {"democracia cristiana", "partido socialista", "partido por la democracia",
                        "yasna provoste", "carolina tohá", "michelle bachelet", "paula narváez",
                        "álvaro elizalde"},
}
BLOC_OF = {name: b for b, names in BLOCS.items() for name in names}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import duckdb
    import networkx as nx

    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET enable_progress_bar=false")

    # ── CHECK 1: comunidades vs coaliciones ──────────────────────────────
    print("=" * 70)
    print("CHECK 1 — COMUNIDADES vs COALICIONES (Louvain sobre aliados)")
    print("=" * 70)
    # top actores no-genéricos
    top = con.execute(
        "SELECT node_id, canonical FROM nodes WHERE lower(canonical) NOT IN "
        f"({','.join('?' * len(GENERICS))}) ORDER BY degree DESC LIMIT 90", list(GENERICS)).fetchall()
    keep = {nid for nid, _ in top}
    name = {nid: c for nid, c in top}
    # pares no-ordenados: pos vs neg
    pair = defaultdict(lambda: [0, 0])
    for f, t, pol in con.execute(
            "SELECT from_node_id, to_node_id, polarity FROM edges").fetchall():
        if f in keep and t in keep:
            k = tuple(sorted((f, t)))
            pair[k][0 if pol == "positive" else 1] += 1 if pol in ("positive", "negative") else 0
    G = nx.Graph()
    G.add_nodes_from(keep)
    for (a, b), (pos, neg) in pair.items():
        if pos > neg:  # relación de aliados (neta positiva)
            G.add_edge(a, b, weight=pos - neg)
    comms = nx.community.louvain_communities(G, weight="weight", seed=42)
    comms = sorted([c for c in comms if len(c) >= 3], key=len, reverse=True)
    for i, c in enumerate(comms[:6]):
        labels = [BLOC_OF.get(name[n].lower(), "·") for n in c]
        from collections import Counter
        dom = Counter(l for l in labels if l != "·").most_common(1)
        domlbl = dom[0][0] if dom else "?"
        members = sorted((name[n] for n in c), key=lambda x: x.lower())
        print(f"\n  Comunidad {i+1} (n={len(c)}, dominante: {domlbl}):")
        print("    " + ", ".join(m[:24] for m in members[:14]))

    # ── CHECK 2: signo por díadas ────────────────────────────────────────
    print("\n" + "=" * 70)
    print("CHECK 2 — SIGNO POR DÍADAS CONOCIDAS (Σ signo; - = antagonismo)")
    print("=" * 70)
    def node(canon):
        r = con.execute("SELECT node_id FROM nodes WHERE canonical=? LIMIT 1", [canon]).fetchone()
        return r[0] if r else None
    def net(a_canon, b_canon):
        a, b = node(a_canon), node(b_canon)
        if not a or not b:
            return None
        row = con.execute(
            "SELECT sum(CASE polarity WHEN 'positive' THEN 1 WHEN 'negative' THEN -1 ELSE 0 END), count(*) "
            "FROM edges WHERE (from_node_id=? AND to_node_id=?) OR (from_node_id=? AND to_node_id=?)",
            [a, b, b, a]).fetchone()
        return row
    dyads = [
        ("Sebastián Piñera", "Gabriel Boric Font", "neg (rivales)"),
        ("Gobierno de Chile", "Gabriel Boric Font", "neg (gob vs oposición)"),
        ("Gobierno de Chile", "Frente Amplio", "neg (gob vs oposición)"),
        ("Unión Demócrata Independiente", "Renovación Nacional", "pos (aliados Chile Vamos)"),
        ("Gabriel Boric Font", "Camila Vallejo", "pos (aliados AD)"),
        ("Daniel Jadue", "Gabriel Boric Font", "pos/comp (primarias AD)"),
        ("José Antonio Kast", "Gabriel Boric Font", "neg (2da vuelta 2021)"),
    ]
    for a, b, exp in dyads:
        r = net(a, b)
        if r and r[1]:
            s, n = r
            sign = "+" if s > 0 else ("-" if s < 0 else "0")
            print(f"  {sign} (Σ{s:+d}, n={n:>4})  {a[:26]} ↔ {b[:22]:22s} | esperado: {exp}")
        else:
            print(f"  (sin aristas)  {a} ↔ {b}")

    # ── CHECK 3: polarización temporal ───────────────────────────────────
    print("\n" + "=" * 70)
    print("CHECK 3 — POLARIZACIÓN TEMPORAL (% aristas negativas por mes)")
    print("=" * 70)
    rows = con.execute(
        "SELECT strftime(publish_date, '%Y-%m') ym, "
        "100.0*sum(CASE WHEN polarity='negative' THEN 1 ELSE 0 END)/count(*) pct_neg, count(*) n "
        "FROM edges WHERE publish_date IS NOT NULL GROUP BY ym ORDER BY ym").fetchall()
    hitos = {"2019-10": "ESTALLIDO", "2020-10": "PLEBISCITO", "2021-12": "2da vuelta", "2022-09": "RECHAZO"}
    mx = max(p for _, p, _ in rows) if rows else 1
    for ym, pct, n in rows:
        if ym < "2019-01" or ym > "2022-12":
            continue
        bar = "█" * int(28 * pct / mx)
        tag = f"  ← {hitos[ym]}" if ym in hitos else ""
        print(f"  {ym}  {pct:4.0f}% {bar}{tag}")
    con.close()
    print("\nVeredicto: revisar si (1) los clusters separan derecha/izquierda, (2) los signos")
    print("siguen la columna 'esperado', (3) los picos de negatividad caen en los hitos.")


if __name__ == "__main__":
    main()
