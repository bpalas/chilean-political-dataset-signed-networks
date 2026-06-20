"""Capa 1 de la curación — propuesta DETERMINISTA de merges de nodos (PREVIEW).

NO toca graph.duckdb. Detecta nodos que son el mismo actor por evidencia determinista
(sin LLM, sin riesgo) y escribe las propuestas a curation/deterministic_merges.json para
revisión. La Capa 3 (Sonnet) se ocupa del grey-zone semántico que esto NO captura.

Tres fuentes de equivalencia (unidas por union-find; superviviente = mayor grado):
  (a) canónico exacto normalizado   — dos nodos con el mismo canonical (Boric ×4, Senado ×4)
  (b) diccionario de siglas curado  — UDI↔Unión Demócrata Independiente, etc. (no fuzzy)
  (c) alias distintivo compartido   — mismo nombre completo (≥2 tokens, ≥8 chars) y mismo
                                      tipo → mismo actor. Reportado aparte para eyeball.

Uso:
    python scripts/curate_propose.py                  # preview + escribe propuestas
    python scripts/curate_propose.py --apply          # copia a curations.json (luego curate_apply.py)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data/processed/graph.duckdb"
CUR_DIR = ROOT / "data/processed/curation"
OUT = CUR_DIR / "deterministic_merges.json"

# Siglas chilenas curadas (sigla_norm → nombre_completo_norm). NO se pueden fuzzy-matchear
# (UDI vs RN serían ~0% similares aunque ambos partidos), por eso van por diccionario.
SIGLAS = {
    "udi": "union democrata independiente",
    "rn": "renovacion nacional",
    "dc": "democracia cristiana",
    "pdc": "democracia cristiana",
    "ps": "partido socialista",
    "ppd": "partido por la democracia",
    "pc": "partido comunista de chile",
    "pcch": "partido comunista de chile",
    "rd": "revolucion democratica",
    "fa": "frente amplio",
    "prsd": "partido radical socialdemocrata",
    "frvs": "federacion regionalista verde social",
    "cs": "convergencia social",
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="copiar las propuestas a curations.json (luego correr curate_apply.py)")
    args = ap.parse_args()

    import duckdb
    from text2sg.er import normalize

    con = duckdb.connect(str(DB), read_only=True)
    nodes = {nid: {"canonical": c, "type": t, "degree": d, "n": m} for nid, c, t, d, m in
             con.execute("SELECT node_id, canonical, node_type, degree, n_mentions FROM nodes").fetchall()}
    alias_norm2nodes: dict[str, set] = defaultdict(set)
    for nid, sn in con.execute("SELECT node_id, surface_norm FROM aliases").fetchall():
        if sn:
            alias_norm2nodes[sn].add(nid)
    con.close()

    # union-find
    parent = {nid: nid for nid in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reason: dict[str, str] = {}

    def union(a, b, why):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            reason.setdefault(b, why)
            reason.setdefault(a, why)

    # índice canónico-normalizado → nodos
    key2nodes: dict[str, list] = defaultdict(list)
    for nid, n in nodes.items():
        key2nodes[normalize(n["canonical"])].append(nid)

    # (a) canónico exacto
    for key, ids in key2nodes.items():
        for o in ids[1:]:
            union(ids[0], o, "canonical-exacto")

    # (b) siglas (canonical o alias == sigla) ↔ nombre completo
    for sigla, full in SIGLAS.items():
        full_nodes = key2nodes.get(full, [])
        if not full_nodes:
            continue
        cand = set(key2nodes.get(sigla, [])) | alias_norm2nodes.get(sigla, set())
        for nid in cand:
            union(full_nodes[0], nid, f"sigla:{sigla}")

    # (c) alias distintivo compartido (nombre completo, mismo tipo)
    shared = []
    for sn, ids in alias_norm2nodes.items():
        if len(ids) < 2 or len(sn.split()) < 2 or len(sn) < 8:
            continue
        by_type: dict[str, list] = defaultdict(list)
        for nid in ids:
            by_type[nodes[nid]["type"]].append(nid)
        for typ, group in by_type.items():
            if len(group) > 1:
                for o in group[1:]:
                    union(group[0], o, f"alias:{sn[:24]}")
                    shared.append((sn, group))

    # construir grupos → merges (superviviente = mayor grado)
    groups: dict[str, list] = defaultdict(list)
    for nid in nodes:
        groups[find(nid)].append(nid)

    merges = []
    for _, ids in groups.items():
        if len(ids) < 2:
            continue
        surv = max(ids, key=lambda i: nodes[i]["degree"])
        sc, st = nodes[surv]["canonical"], nodes[surv]["type"]
        for nid in ids:
            if nid != surv:
                merges.append({"node_id": nid, "merge_into": surv, "canonical": sc, "type": st,
                               "is_generic": False, "_absorbed": nodes[nid]["canonical"],
                               "_deg": nodes[nid]["degree"], "_surv_deg": nodes[surv]["degree"],
                               "_reason": reason.get(nid, "?")})

    # ── preview ──
    by_reason = defaultdict(int)
    for m in merges:
        by_reason[m["_reason"].split(":")[0]] += 1
    print(f"Nodos: {len(nodes):,} | grupos con merge: "
          f"{sum(1 for ids in groups.values() if len(ids) > 1)} | nodos absorbidos: {len(merges)}")
    print(f"Por fuente: {dict(by_reason)}\n")
    # agrupar por superviviente para mostrar
    bysurv = defaultdict(list)
    for m in merges:
        bysurv[m["merge_into"]].append(m)
    shown = sorted(bysurv.items(), key=lambda kv: -nodes[kv[0]]["degree"])
    print("=== MERGES PROPUESTOS (top 30 por grado del superviviente) ===")
    for surv, ms in shown[:30]:
        sc = nodes[surv]["canonical"]
        absorbed = ", ".join(f"{m['_absorbed']}(deg {m['_deg']},{m['_reason']})" for m in ms)
        print(f"  ← {sc} [deg {nodes[surv]['degree']}]\n      absorbe: {absorbed}")

    CUR_DIR.mkdir(parents=True, exist_ok=True)
    clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in merges]
    OUT.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nPropuestas escritas → {OUT.relative_to(ROOT)} ({len(clean)} merges)")
    print("Revisar y luego: python scripts/curate_propose.py --apply  &&  python scripts/curate_apply.py")

    if args.apply:
        (CUR_DIR / "curations.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✓ copiado a curations.json — ahora: python scripts/curate_apply.py")


if __name__ == "__main__":
    main()
