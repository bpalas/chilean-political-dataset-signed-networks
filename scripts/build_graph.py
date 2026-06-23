"""Loader determinístico — puebla graph.duckdb desde NER + ER + RE.

Orden (respeta FKs): runs → articles → nodes → aliases → mentions → edges.
Idempotente: reinicia la DB desde el esquema. Mapea cada surface a node_id vía el
índice normalizado del ER (resolution_80k.json).

Uso: python scripts/build_graph.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from text2sg.er import normalize  # noqa: E402
from text2sg.graph_db import init_db  # noqa: E402

D = ROOT / "data/processed"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolution", default=str(D / "er/resolution_80k.json"))
    ap.add_argument("--samples", nargs="+", default=["political_2019_2022_80k"])
    ap.add_argument("--no-edges", action="store_true",
                    help="no cargar edges acá (se cargan con load_gemini_edges)")
    args = ap.parse_args()

    res = json.loads(Path(args.resolution).read_text(encoding="utf-8"))
    nodes = res["nodes"]
    assign = res["assign"]                       # surface(raw) → node_id
    norm2node: dict[str, str] = {}               # norm(alias) → node_id (para relaciones)
    for n in nodes:
        for a in n["aliases"]:
            norm2node.setdefault(normalize(a), n["node_id"])

    con = init_db()
    print("DB inicializada. Cargando…", flush=True)

    # runs
    con.execute("""INSERT INTO runs (run_id,kind,model,genome_id,prompt_id,params,n_items,notes) VALUES
      ('ner-gliner','ner','urchade/gliner_multi-v2.1',NULL,NULL,'{"threshold":0.4}',80000,'NER 80k'),
      ('re-haikuGE','re','claude-haiku-4-5','haiku_ge_best','haiku_ge_best','{"group":5}',200,'RE muestra'),
      ('er-v1','er',NULL,NULL,NULL,'{"fuzzy_cutoff":90,"blocking":"token"}',96990,'ER blocking')""")

    # articles (unión de muestras, con body)
    samp = pd.concat(
        [pd.read_parquet(D / f"samples/{s}.parquet",
                         columns=["article_id", "title", "body", "source", "publish_date", "year"])
         for s in args.samples], ignore_index=True).drop_duplicates("article_id").reset_index(drop=True)
    samp["publish_date"] = pd.to_datetime(samp["publish_date"], errors="coerce")
    samp["period"] = samp.apply(
        lambda r: (f"{int(r['year'])}-H{1 if pd.notna(r['publish_date']) and r['publish_date'].month <= 6 else 2}"
                   if pd.notna(r["year"]) else None), axis=1)
    samp["body_tokens"] = samp["body"].str.split().str.len()
    samp["publish_date"] = samp["publish_date"].dt.date
    con.register("samp", samp[["article_id", "title", "body", "body_tokens", "source", "publish_date", "year", "period"]])
    con.execute("INSERT INTO articles SELECT * FROM samp")
    print(f"  articles: {len(samp):,}", flush=True)

    # nodes
    ndf = pd.DataFrame([{"node_id": n["node_id"], "canonical": n["canonical"], "node_type": n["type"],
                         "role": None, "n_mentions": n["n"], "n_articles": 0, "degree": 0,
                         "first_seen": None, "last_seen": None, "curated": False, "confidence": 1.0}
                        for n in nodes])
    con.register("ndf", ndf)
    con.execute("INSERT INTO nodes SELECT * FROM ndf")
    print(f"  nodes: {len(ndf):,}", flush=True)

    # aliases (UNIQUE(surface_norm) → dedup)
    adf = pd.DataFrame([{"alias_id": i, "node_id": n["node_id"], "surface_form": a,
                         "surface_norm": normalize(a), "source": "ner", "n_occurrences": 0}
                        for i, (n, a) in enumerate((n, a) for n in nodes for a in n["aliases"])])
    adf = adf.drop_duplicates("surface_norm").reset_index(drop=True)
    adf["alias_id"] = range(len(adf))
    con.register("adf", adf)
    con.execute("INSERT INTO aliases SELECT alias_id,node_id,surface_form,surface_norm,source,n_occurrences FROM adf")
    print(f"  aliases: {len(adf):,}", flush=True)

    # mentions (re-leer NER 80k → node_id vía assign/norm)
    rows = []
    for s in glob.glob(str(D / "ner/gliner/year=*/part-*.parquet")):
        df = pd.read_parquet(s)
        for aid, ents in zip(df["article_id"], df["entities"]):
            for e in json.loads(ents):
                nid = assign.get(e["text"]) or norm2node.get(normalize(e["text"]))
                if not nid:
                    continue
                sp = e.get("char_span") or [None, None]
                rows.append((nid, aid, "ner-gliner", e["text"], sp[0], sp[1], e.get("score"), "exact"))
    mdf = pd.DataFrame(rows, columns=["node_id", "article_id", "run_id", "surface_form",
                                      "char_start", "char_end", "ner_score", "resolved_by"])
    mdf.insert(0, "mention_id", range(len(mdf)))
    mdf["match_score"] = None
    con.register("mdf", mdf)
    con.execute("""INSERT INTO mentions SELECT mention_id,node_id,article_id,run_id,surface_form,
                   char_start,char_end,ner_score,resolved_by,match_score FROM mdf
                   WHERE article_id IN (SELECT article_id FROM articles)""")
    print(f"  mentions: {len(mdf):,}", flush=True)

    # edges (RE muestra → node_id)
    if args.no_edges:
        print("  (edges se cargan con load_gemini_edges) ✓ base poblada.", flush=True)
        return
    rel = pd.read_parquet(D / "re/relations.parquet")
    erows = []
    for r in rel.itertuples():
        fn, tn = norm2node.get(normalize(r.from_entity)), norm2node.get(normalize(r.to_entity))
        if fn and tn and fn != tn:
            pd_ = r.publish_date if not pd.isna(r.publish_date) else None
            erows.append((fn, tn, r.article_id, "re-haikuGE", r.act_type, r.polarity,
                          r.issue, r.evidence_quote, None, pd_, None))
    edf = pd.DataFrame(erows, columns=["from_node_id", "to_node_id", "article_id", "run_id", "act_type",
                                       "polarity", "issue", "evidence_quote", "confidence", "publish_date", "period"])
    edf = edf.drop_duplicates(["from_node_id", "to_node_id", "article_id", "act_type", "run_id"]).reset_index(drop=True)
    edf.insert(0, "edge_id", range(len(edf)))
    con.register("edf", edf)
    con.execute("""INSERT INTO edges SELECT edge_id,from_node_id,to_node_id,article_id,run_id,act_type,
                   polarity,issue,evidence_quote,confidence,publish_date,period FROM edf
                   WHERE article_id IN (SELECT article_id FROM articles)""")
    print(f"  edges: {len(edf):,}", flush=True)

    # degree pre-computado
    con.execute("""UPDATE nodes SET degree=(SELECT count(*) FROM edges e
                   WHERE e.from_node_id=nodes.node_id OR e.to_node_id=nodes.node_id)""")
    print("  degree actualizado. ✓ graph.duckdb poblado.")


if __name__ == "__main__":
    main()
