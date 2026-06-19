"""Entity Resolution (Pasada 2) — colapsa surface forms en nodos canónicos.

Precision-first: el peor error es FUSIONAR dos actores distintos (contamina toda la red),
así que ante la duda se dejan nodos separados. Cuatro defensas:
  1. Normalización (lower, sin acentos) → "Gobierno"/"gobierno" colapsan solos.
  2. Gazetteer de aliases conocidos (seed clivaje + proto Haiku) → canonicaliza.
  3. Fuzzy con CROSS-TYPE BLOCKING → nunca fusiona tipos distintos (person≠institution).
  4. Umbral conservador (≥90) → preferir dos nodos a una fusión incorrecta.

Los surface forms que no están en el gazetteer se CLUSTERIZAN entre sí (no se duplican):
los frecuentes anclan primero (orden por frecuencia desc).

Funciones puras (testeables): resolve_mentions toma listas y devuelve asignación + nodos.
"""
from __future__ import annotations

from typing import Optional

from text2sg.er import normalize


def build_alias_gazetteer(seed_names: list[str], proto_entries: list[dict]) -> dict[str, str]:
    """norm(alias) → canonical conocido. seed = nombres clivaje (canonical = ellos mismos);
    proto = entidades Haiku con surface_forms (todas mapean a su canonical)."""
    gz: dict[str, str] = {}
    for e in proto_entries:
        canon = (e.get("canonical") or "").strip()
        if not canon:
            continue
        for a in {canon, *e.get("surface_forms", [])}:
            k = normalize(a)
            if k:
                gz.setdefault(k, canon)
    for name in seed_names:
        k = normalize(name)
        if k:
            gz.setdefault(k, name)
    return gz


def _fuzzy(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz
        return int(fuzz.token_sort_ratio(a, b))
    except ImportError:
        return 100 if a == b else 0


def _surname_ok(a_norm: str, b_norm: str, cutoff: int = 88) -> bool:
    """Guarda anti-sobre-fusión para personas: el apellido (último token) debe ser muy
    similar. Separa 'alberto espina' vs 'alberto espinoza' (apellidos distintos) pero
    mantiene 'teodoro ribera' vs 'teodoro ribiera' (typo del mismo apellido)."""
    ta, tb = a_norm.split(), b_norm.split()
    if not ta or not tb:
        return True
    return _fuzzy(ta[-1], tb[-1]) >= cutoff


def resolve_mentions(
    mentions: list[tuple[str, str, int]],
    alias_gazetteer: dict[str, str] | None = None,
    *,
    fuzzy_cutoff: int = 90,
    min_token_len: int = 4,
) -> tuple[dict[str, str], list[dict]]:
    """Resuelve menciones → nodos canónicos.

    `mentions`: lista de (surface_form, type, freq). `type` puede ser 'unknown'.
    Devuelve (asignación {surface: node_id}, nodos [{node_id, canonical, type, aliases, n}]).

    Clustering incremental precision-first: orden por freq desc (los actores principales
    anclan primero), exacto → gazetteer → fuzzy cross-type (≥cutoff) → nodo nuevo.
    """
    gz = alias_gazetteer or {}
    nodes: list[dict] = []
    norm2node: dict[str, int] = {}        # norm(surface) ya visto → índice de nodo
    token_index: dict[str, set] = {}      # token (≥4) → {índices de nodo que lo contienen}
    assign: dict[str, str] = {}

    def _index(idx: int, ns: str) -> None:
        for t in ns.split():
            if len(t) >= min_token_len:
                token_index.setdefault(t, set()).add(idx)

    for surf, typ, freq in sorted(mentions, key=lambda m: -m[2]):
        ns = normalize(surf)
        if not ns:
            continue
        # 1. exacto contra lo ya resuelto
        idx = norm2node.get(ns)
        # 2. fuzzy SOLO contra candidatos del bloque (nodos que comparten un token ≥4),
        #    mismo tipo (cross-type blocking) y, en personas, apellido coincidente.
        if idx is None:
            cand: set = set()
            for t in ns.split():
                if len(t) >= min_token_len:
                    cand |= token_index.get(t, set())
            best, bs = None, 0
            for ci in cand:
                node = nodes[ci]
                if node["type"] != typ and "unknown" not in (node["type"], typ):
                    continue
                is_person = "person" in (node["type"], typ)
                for a in node["_norm"]:
                    s = _fuzzy(ns, a)
                    if s > bs and (not is_person or _surname_ok(ns, a)):
                        bs, best = s, ci
            if bs >= fuzzy_cutoff:
                idx = best
        # 3. nodo nuevo
        if idx is None:
            idx = len(nodes)
            nodes.append({"node_id": f"N{idx:05d}", "canonical": gz.get(ns, surf),
                          "type": typ, "aliases": {surf}, "_norm": {ns}, "n": 0})
        node = nodes[idx]
        node["aliases"].add(surf)
        node["_norm"].add(ns)
        node["n"] += freq
        if ns in gz and node["canonical"] == surf:
            node["canonical"] = gz[ns]
        _index(idx, ns)
        norm2node[ns] = idx
        assign[surf] = node["node_id"]

    for n in nodes:
        n["aliases"] = sorted(n["aliases"])
        del n["_norm"]
    return assign, nodes
