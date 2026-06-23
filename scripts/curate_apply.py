"""Aplica curations.json (Sonnet) a graph.duckdb — determinístico.

Merges: mueve aliases/mentions/edges del nodo absorbido al representante, manejando los
constraints (UNIQUE surface_norm en aliases, UNIQUE en edges). Updates: canonical, tipo,
curated=TRUE; genéricos → confidence 0.3. Recomputa n_mentions y degree.

Uso: python scripts/curate_apply.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"
CUR = ROOT / "data/processed/curation/curations.json"


def main() -> None:
    import duckdb
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cur = json.loads(CUR.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB))

    # Mapa de merges (absorbed → representante), resuelto transitivamente.
    raw = {c["node_id"]: c["merge_into"] for c in cur
           if c.get("merge_into") and c["merge_into"] != c["node_id"]}
    def root(x):
        seen = set()
        while x in raw and x not in seen:
            seen.add(x); x = raw[x]
        return x
    merge = {a: root(a) for a in raw}

    # Guarda precision-first sobre la curación LLM: NO fusionar dos canonicals ambos
    # largos (ninguno es sigla) y muy distintos — el LLM puede sobre-fusionar
    # ("Congreso Nacional" vs "Senado"). Las siglas (DC↔Democracia Cristiana) pasan
    # porque la sigla es corta (≤5).
    from rapidfuzz import fuzz
    canon = {c["node_id"]: (c.get("canonical") or "") for c in cur}
    safe, blocked = {}, []
    for a, surv in merge.items():
        ca, cb = canon.get(a, ""), canon.get(surv, "")
        if min(len(ca), len(cb)) > 5 and fuzz.token_sort_ratio(ca.lower(), cb.lower()) < 60:
            blocked.append(f"{ca} ✕ {cb}")
        else:
            safe[a] = surv
    merge = safe
    if blocked:
        print(f"merges BLOQUEADOS (canonicals distintos): {blocked}", flush=True)
    print(f"curaciones: {len(cur)} | merges aceptados: {len(merge)} | "
          f"genéricos: {sum(1 for c in cur if c.get('is_generic'))}", flush=True)

    # 1. aliases: borrar colisiones de surface_norm, luego mover al representante
    for absorbed, surv in merge.items():
        con.execute("""DELETE FROM aliases WHERE node_id=? AND surface_norm IN
                       (SELECT surface_norm FROM aliases WHERE node_id=?)""", [absorbed, surv])
        con.execute("UPDATE aliases SET node_id=? WHERE node_id=?", [surv, absorbed])

    # 2. mentions: mover (sin UNIQUE → directo)
    for absorbed, surv in merge.items():
        con.execute("UPDATE mentions SET node_id=? WHERE node_id=?", [surv, absorbed])

    # 3. edges: remapear en memoria + dedup (evita choques con UNIQUE) + reescribir
    e = con.execute("SELECT * FROM edges").df()
    if len(e):
        e["from_node_id"] = e["from_node_id"].replace(merge)
        e["to_node_id"] = e["to_node_id"].replace(merge)
        e = e[e.from_node_id != e.to_node_id]
        e = e.drop_duplicates(["from_node_id", "to_node_id", "article_id", "act_type", "run_id"])
        con.execute("DELETE FROM edges")
        con.register("e_df", e)
        con.execute("INSERT INTO edges SELECT * FROM e_df")

    # 4. updates de canonical/tipo/curated (solo sobrevivientes)
    for c in cur:
        if c["node_id"] in merge:
            continue
        conf = 0.3 if c.get("is_generic") else 1.0
        con.execute("UPDATE nodes SET canonical=?, node_type=?, curated=TRUE, confidence=? WHERE node_id=?",
                    [c["canonical"], c["type"], conf, c["node_id"]])

    # 5. sumar n_mentions de absorbidos al representante, luego borrarlos
    for absorbed, surv in merge.items():
        con.execute("""UPDATE nodes SET n_mentions = n_mentions +
                       COALESCE((SELECT n_mentions FROM nodes WHERE node_id=?),0) WHERE node_id=?""",
                    [absorbed, surv])
        con.execute("DELETE FROM nodes WHERE node_id=?", [absorbed])

    # 6. recomputar degree (rápido: agregación UNION ALL + UPDATE FROM, no join OR)
    con.execute("""CREATE OR REPLACE TEMP TABLE _deg AS
                   SELECT nid, count(*) c FROM (
                     SELECT from_node_id nid FROM edges UNION ALL SELECT to_node_id FROM edges
                   ) GROUP BY nid""")
    con.execute("UPDATE nodes SET degree=0")
    con.execute("UPDATE nodes SET degree=_deg.c FROM _deg WHERE nodes.node_id=_deg.nid")

    n_nodes = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
    n_cur = con.execute("SELECT count(*) FROM nodes WHERE curated").fetchone()[0]
    print(f"✓ aplicado. nodos: {n_nodes:,} (curados: {n_cur}) | merges aplicados: {len(merge)}")


if __name__ == "__main__":
    main()
