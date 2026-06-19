"""Scorer del test con gold (RE) — compara predicciones del extractor vs gold v2.

Mapea cada actor predicho (nombre) → código de unión U_k del gold (vía surfaces,
exacto o fuzzy ≥88), forma las tripletas y mide P/R/f0.5 en niveles crecientes de
exigencia. f0.5 pesa 2× la precisión (un FP contamina la red signada).

Uso: python scripts/score_gold.py --preds data/processed/gold_test/preds.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from text2sg.er import normalize  # noqa: E402

GT = ROOT / "data/processed/gold_test"


def _fuzzy(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz
        return int(fuzz.token_sort_ratio(a, b))
    except ImportError:
        return 100 if a == b else 0


def name_to_u(name: str, art_unions: dict, cutoff: int = 88) -> str | None:
    """Resuelve un nombre predicho al código U_k del gold de ese artículo."""
    nn = normalize(name)
    best, bs = None, 0
    for uid, info in art_unions.items():
        for s in info.get("surfaces", []) + info.get("canonical_names", []):
            sc = _fuzzy(nn, normalize(s))
            if sc > bs:
                bs, best = sc, uid
    return best if bs >= cutoff else None


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f05 = (1.25 * p * r / (0.25 * p + r)) if (0.25 * p + r) else 0.0
    return p, r, f05


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default=str(GT / "preds.json"))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    preds = json.loads(Path(args.preds).read_text(encoding="utf-8"))
    if isinstance(preds, list):
        preds = {p["article_id"]: p.get("relations", []) for p in preds}
    gold = json.loads((GT / "gold.json").read_text(encoding="utf-8"))
    unions = json.loads((GT / "unions.json").read_text(encoding="utf-8"))

    levels = {"undirected": set, "directed": None, "+act_type": None, "+polarity": None}
    agg = {k: [0, 0, 0] for k in levels}  # tp, fp, fn

    for aid, gold_rels in gold.items():
        u = unions.get(aid, {})
        def keys(rels, is_pred):
            out = {"undirected": set(), "directed": set(), "+act_type": set(), "+polarity": set()}
            for r in rels:
                if is_pred:
                    a, b = name_to_u(r.get("from_entity", ""), u), name_to_u(r.get("to_entity", ""), u)
                else:
                    a, b = r["u_from"], r["u_to"]
                if not a or not b or a == b:
                    continue
                act, pol = r.get("act_type", ""), r.get("polarity", "")
                out["undirected"].add(frozenset((a, b)))
                out["directed"].add((a, b))
                out["+act_type"].add((a, b, act))
                out["+polarity"].add((a, b, act, pol))
            return out
        P, G = keys(preds.get(aid, []), True), keys(gold_rels, False)
        for lv in levels:
            tp = len(P[lv] & G[lv]); fp = len(P[lv] - G[lv]); fn = len(G[lv] - P[lv])
            agg[lv][0] += tp; agg[lv][1] += fp; agg[lv][2] += fn

    print(f"=== Test con gold (RE) — {len(gold)} art, {sum(len(v) for v in gold.values())} rel gold ===")
    print(f"{'nivel':14s} {'P':>6s} {'R':>6s} {'f0.5':>6s}   (tp/fp/fn)")
    for lv in levels:
        tp, fp, fn = agg[lv]
        p, r, f = prf(tp, fp, fn)
        print(f"{lv:14s} {p:6.3f} {r:6.3f} {f:6.3f}   ({tp}/{fp}/{fn})")
    print("\nReferencia paper: id15 f0.5 0.928 / haiku_ge_best ~0.928 (directed+labeled).")


if __name__ == "__main__":
    main()
