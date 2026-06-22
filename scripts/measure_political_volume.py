"""Mide el volumen de artículos POLÍTICOS por año en todo el lake (prefiltro gaz+léxico).

Cuenta, sin materializar, cuántos artículos pasan el prefiltro político por año. Sirve
para dimensionar una ventana ampliada (2014-2026). OJO: con el gazetteer actual (afinado
a 2019-2022) los años de fuera salen SUB-contados → marca dónde enriquecer.

Uso: python scripts/measure_political_volume.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LAKE = ROOT / "data/raw/corpus/news/articles"
GAZ = ROOT / "data/processed/gazetteer.json"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import duckdb
    from text2sg.corpus_data import _actor_regex, build_political_lexicon

    gaz = json.loads(GAZ.read_text(encoding="utf-8"))
    lex = build_political_lexicon()
    rx_a, rx_l = _actor_regex(gaz), _actor_regex(lex)
    glob = str(LAKE / "**" / "*.parquet").replace("\\", "/")

    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    t0 = time.time()
    q = f"""
      SELECT year, count(*) total,
             sum(CASE WHEN na >= 2 OR nl >= 3 THEN 1 ELSE 0 END) pol
      FROM (
        SELECT year,
          len(list_distinct(regexp_extract_all(lower(coalesce(title,'') || ' ' || body), ?))) na,
          len(list_distinct(regexp_extract_all(lower(coalesce(title,'') || ' ' || body), ?))) nl
        FROM read_parquet('{glob}', hive_partitioning=true)
        WHERE body IS NOT NULL AND length(trim(body)) > 0
      ) GROUP BY year ORDER BY year
    """
    rows = con.execute(q, [rx_a, rx_l]).fetchall()
    con.close()

    print(f"{'año':>6} {'total':>10} {'políticos':>11} {'%':>5}")
    tt = tp = 0
    for y, total, pol in rows:
        pol = pol or 0
        tt += total; tp += pol
        flag = " ←2019-2022" if 2019 <= y <= 2022 else ""
        print(f"  {y:>4} {total:>10,} {pol:>11,} {100*pol/total:>4.0f}%{flag}")
    print(f"  {'TOTAL':>4} {tt:>10,} {tp:>11,} {100*tp/tt:>4.0f}%")
    print(f"\n({time.time()-t0:.0f}s)  Nota: 2014-2018 y 2023-2026 sub-contados (gazetteer 2019-2022).")


if __name__ == "__main__":
    main()
