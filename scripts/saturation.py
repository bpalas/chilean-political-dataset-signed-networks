"""Test de saturación — ¿cuántos artículos (NER) necesitamos realmente?

Submuestrea el grafo ACTUAL a fracciones crecientes de artículos y mide cuánto se
estabiliza la red signada persona↔persona. Si de 75%→100% ya no cambia, más datos
(doblar) es redundante; si sigue creciendo, doblar paga. Extrapola el valor marginal
de duplicar.

Métricas por fracción:
  - díadas estables (≥3 aristas valenciadas)  → cobertura
  - correlación del signo de díada vs el 100% → estabilidad de la estructura

Uso: python scripts/saturation.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"


def afrac(aid: str) -> float:
    """Fracción uniforme [0,1) determinista por article_id (hash)."""
    return (int(hashlib.md5(aid.encode()).hexdigest()[:8], 16) % 100000) / 100000.0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import duckdb
    import pandas as pd

    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET enable_progress_bar=false")
    df = con.execute("""
        SELECT e.article_id AS aid, e.from_node_id AS f, e.to_node_id AS t,
               CASE e.polarity WHEN 'positive' THEN 1 WHEN 'negative' THEN -1 ELSE 0 END AS sign
        FROM edges e
        JOIN nodes nf ON e.from_node_id = nf.node_id AND nf.node_type = 'person'
        JOIN nodes nt ON e.to_node_id = nt.node_id AND nt.node_type = 'person'
    """).df()
    con.close()

    df["dyad"] = [tuple(sorted((a, b))) for a, b in zip(df["f"], df["t"])]
    df["af"] = df["aid"].map(afrac)
    print(f"aristas persona↔persona: {len(df):,} | díadas únicas: {df['dyad'].nunique():,}\n")

    def stable_dyads(sub: pd.DataFrame) -> dict:
        v = sub[sub["sign"] != 0]
        g = v.groupby("dyad")["sign"].agg(["sum", "count"])
        g = g[g["count"] >= 3]
        return {d: s / c for d, (s, c) in zip(g.index, g[["sum", "count"]].values)}

    full = stable_dyads(df)  # referencia 100%
    print(f"{'frac':>5} {'artículos':>10} {'díadas≥3':>9} {'%cobertura':>10} {'corr_signo_vs100%':>18}")
    prev = None
    for fr in (0.25, 0.50, 0.75, 1.00):
        sub = df[df["af"] < fr]
        n_art = sub["aid"].nunique()
        sd = stable_dyads(sub)
        cov = 100 * len(sd) / len(full)
        # correlación de signo medio entre las díadas comunes con el 100%
        common = [d for d in sd if d in full]
        if common:
            import numpy as np
            a = np.array([sd[d] for d in common])
            b = np.array([full[d] for d in common])
            corr = float(np.corrcoef(a, b)[0, 1]) if len(common) > 2 else 1.0
        else:
            corr = 0.0
        growth = f"  (+{len(sd)-prev:,} díadas vs frac previa)" if prev is not None else ""
        print(f"{fr:>5.2f} {n_art:>10,} {len(sd):>9,} {cov:>9.0f}% {corr:>17.4f}{growth}")
        prev = len(sd)

    print("\nLectura: si 'díadas≥3' sigue subiendo fuerte de 0.75→1.00, DOBLAR agrega cobertura")
    print("(nuevas díadas robustas). Si se aplana y corr≈1.0, la estructura ya está saturada.")


if __name__ == "__main__":
    main()
