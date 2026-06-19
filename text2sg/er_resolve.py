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
) -> tuple[dict[str, str], list[dict]]:
    """Resuelve menciones → nodos canónicos.

    `mentions`: lista de (surface_form, type, freq). `type` puede ser 'unknown'.
    Devuelve (asignación {surface: node_id}, nodos [{node_id, canonical, type, aliases, n}]).

    Clustering incremental precision-first: orden por freq desc (los actores principales
    anclan primero), exacto → gazetteer → fuzzy cross-type (≥cutoff) → nodo nuevo.
    """
    gz = alias_gazetteer or {}
    nodes: list[dict] = []
    norm2node: dict[str, str] = {}        # norm(surface) ya visto → node_id
    assign: dict[str, str] = {}

    def _new_node(canonical: str, ntype: str, surface: str) -> str:
        nid = f"N{len(nodes):05d}"
        nodes.append({"node_id": nid, "canonical": canonical, "type": ntype,
                      "aliases": {surface}, "n": 0})
        return nid

    for surf, typ, freq in sorted(mentions, key=lambda m: -m[2]):
        ns = normalize(surf)
        if not ns:
            continue
        # 1. exacto contra lo ya resuelto
        nid = norm2node.get(ns)
        # 2. fuzzy contra nodos del MISMO tipo (cross-type blocking), umbral conservador
        if nid is None:
            best_id, best_score = None, 0
            for node in nodes:
                # cross-type: solo comparar si tipos compatibles (o alguno desconocido)
                if node["type"] != typ and "unknown" not in (node["type"], typ):
                    continue
                is_person = "person" in (node["type"], typ)
                for a in node["aliases"]:
                    na = normalize(a)
                    s = _fuzzy(ns, na)
                    # personas: además del score global, el apellido debe coincidir fuerte
                    if s > best_score and (not is_person or _surname_ok(ns, na)):
                        best_score, best_id = s, node["node_id"]
            if best_score >= fuzzy_cutoff:
                nid = best_id
        # 3. nodo nuevo (canonical = el del gazetteer si lo conoce, si no el surface)
        if nid is None:
            nid = _new_node(gz.get(ns, surf), typ, surf)
        # registrar
        assign[surf] = nid
        norm2node[ns] = nid
        node = next(n for n in nodes if n["node_id"] == nid)
        node["aliases"].add(surf)
        node["n"] += freq
        # promover canonical conocido si el gazetteer lo tiene y el actual es un alias suelto
        if ns in gz and node["canonical"] == surf:
            node["canonical"] = gz[ns]

    # aliases set → list ordenada (para serializar)
    for n in nodes:
        n["aliases"] = sorted(n["aliases"])
    return assign, nodes
