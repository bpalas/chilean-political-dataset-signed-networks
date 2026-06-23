"""RE de producción con Gemini Batch API — orquestador.

Subcomandos:
  prepare  → arma el JSONL de entrada (article_id, body, actores del NER+ER, ≥2 actores)
  submit   → sube el JSONL y crea el batch (imprime el batch name → guardar)
  poll     → estado del batch
  fetch    → descarga resultados → relations_gemini.parquet (con gate de evidencia)

La API key se lee de .env (gitignored). Corre en la nube de Google: no compite con el
NER/ER local. Ventana batch ~24h, 50% más barato que sync.

Uso:
  python scripts/run_re_gemini.py prepare
  python scripts/run_re_gemini.py submit            # → guarda el batch name
  python scripts/run_re_gemini.py poll  --name <batch>
  python scripts/run_re_gemini.py fetch --name <batch>
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from text2sg.batch_gemini import (build_jsonl, fetch, load_genome, make_client,  # noqa: E402
                                  poll, submit)
from text2sg.er import normalize  # noqa: E402

D = ROOT / "data/processed"
GEN = D / "re_gemini"
JSONL = GEN / "input.jsonl"
ACTOR_TYPES = {"person", "party", "institution", "coalition", "movement", "org"}


def _bodies(samples: list[str]) -> dict:
    """Une los bodies de varias muestras (article_id → body)."""
    body_of: dict = {}
    for s in samples:
        sd = pd.read_parquet(D / f"samples/{s}.parquet", columns=["article_id", "body"])
        body_of.update(dict(zip(sd.article_id, sd.body)))
    return body_of


def prepare(limit: int | None, genome_path: str | None = None,
            samples: list[str] | None = None, resolution: str | None = None) -> None:
    GEN.mkdir(parents=True, exist_ok=True)
    samples = samples or ["political_2019_2022_80k"]
    res_path = Path(resolution) if resolution else (D / "er/resolution_80k.json")
    res = json.loads(res_path.read_text(encoding="utf-8"))
    assign = res["assign"]
    canon = {n["node_id"]: n["canonical"] for n in res["nodes"]}
    body_of = _bodies(samples)
    print(f"muestras: {samples} | resolución: {res_path.name} | {len(body_of):,} artículos", flush=True)

    items, n_skip = [], 0
    for s in glob.glob(str(D / "ner/gliner/year=*/part-*.parquet")):
        try:  # robusto a shards a medio escribir (el NER full corre en paralelo)
            cols = [pd.read_parquet(s)[c] for c in ("article_id", "entities")]
        except Exception:
            continue
        for aid, ents in zip(*cols):
            body = body_of.get(aid)
            if not body:  # solo los 80k tienen body → los shards del 402k se saltan
                continue
            actors = []
            for e in json.loads(ents):
                if e["type"] in ACTOR_TYPES:
                    nid = assign.get(e["text"])
                    actors.append(canon.get(nid, e["text"]) if nid else e["text"])
            actors = sorted(set(actors))
            if len(actors) >= 2:
                items.append((aid, body, actors))
            else:
                n_skip += 1
            if limit and len(items) >= limit:
                break
        if limit and len(items) >= limit:
            break

    genome = load_genome(genome_path) if genome_path else load_genome()
    print(f"genoma: {Path(genome_path).name if genome_path else 'id15_champion.json'} "
          f"| model {genome['model']}", flush=True)
    build_jsonl(items, genome, JSONL)
    # estimación de costo (tokens ≈ chars/4)
    in_tok = sum(len(genome["prompt_text"]) + len(b[:6000]) + len(", ".join(a)) for _, b, a in items) / 4
    out_tok = len(items) * 600
    print(f"preparado: {len(items):,} artículos (≥2 actores) | saltados {n_skip:,}", flush=True)
    print(f"JSONL: {JSONL}")
    print(f"tokens ~ in {in_tok/1e6:.1f}M / out {out_tok/1e6:.1f}M")
    print(f"costo batch estimado (gemini-2.5-flash, 50% off): "
          f"~${in_tok/1e6*0.15 + out_tok/1e6*0.60:.0f}  "
          f"(flash-lite sería ~${in_tok/1e6*0.05 + out_tok/1e6*0.20:.0f})")


def do_submit(model: str | None, genome_path: str | None = None) -> None:
    cl = make_client()
    genome = load_genome(genome_path) if genome_path else load_genome()
    if model:
        genome["model"] = model
    print(f"submit con model {genome['model']}", flush=True)
    name = submit(cl, JSONL, genome, display="re-80k")
    (GEN / "batch_name.txt").write_text(name, encoding="utf-8")
    print(f"batch creado: {name}\n(guardado en {GEN/'batch_name.txt'})")


def do_poll(name: str | None) -> None:
    name = name or (GEN / "batch_name.txt").read_text(encoding="utf-8").strip()
    print(f"{name}: {poll(make_client(), name)}")


def do_fetch(name: str | None, samples: list[str] | None = None, out: str | None = None) -> None:
    name = name or (GEN / "batch_name.txt").read_text(encoding="utf-8").strip()
    cl = make_client()
    raw = fetch(cl, name)
    body_of = _bodies(samples or ["political_2019_2022_80k"])
    out_path = Path(out) if out else (GEN / "relations_gemini.parquet")
    rows, kept, dropped = [], 0, 0
    for aid, text in raw.items():
        try:
            rels = json.loads(text).get("relations", [])
        except Exception:
            continue
        body = body_of.get(aid, "")
        for r in rels:
            q = (r.get("evidence_quote") or "").strip()
            if len(q) >= 8 and q in body:  # gate de evidencia determinista
                rows.append({"article_id": aid, **{k: r.get(k) for k in
                             ("from_entity", "to_entity", "act_type", "polarity", "issue", "evidence_quote")}})
                kept += 1
            else:
                dropped += 1
    pd.DataFrame(rows).to_parquet(out_path, index=False)
    print(f"fetch: {kept:,} relaciones (gate evidencia) | descartadas {dropped:,} → {out_path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--limit", type=int, default=None)
    p.add_argument("--genome", default=None, help="ruta a genoma (ej. text2sg/prompts/gemini_champion_v2.json)")
    p.add_argument("--samples", nargs="+", default=None, help="muestras a incluir (sin .parquet)")
    p.add_argument("--resolution", default=None, help="ruta a resolution.json del ER")
    s = sub.add_parser("submit"); s.add_argument("--model", default=None, help="override (ej. gemini-2.5-flash-lite)")
    s.add_argument("--genome", default=None, help="ruta a genoma (el model sale del genoma si no hay --model)")
    pl = sub.add_parser("poll"); pl.add_argument("--name", default=None)
    fe = sub.add_parser("fetch"); fe.add_argument("--name", default=None)
    fe.add_argument("--samples", nargs="+", default=None, help="muestras (para el gate de evidencia)")
    fe.add_argument("--out", default=None, help="parquet de salida")
    args = ap.parse_args()
    {"prepare": lambda: prepare(args.limit, args.genome, args.samples, args.resolution),
     "submit": lambda: do_submit(args.model, args.genome),
     "poll": lambda: do_poll(args.name),
     "fetch": lambda: do_fetch(args.name, args.samples, args.out)}[args.cmd]()


if __name__ == "__main__":
    main()
