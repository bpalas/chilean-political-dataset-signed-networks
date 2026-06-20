"""Exporta las tablas del grafo (graph.duckdb) a Parquet → dataset HF-nativo.

El `.duckdb` es la copia de trabajo local (rápida, con vistas). Parquet es el formato
que HF entiende: dataset viewer, `load_dataset`, y SQL remoto con DuckDB vía `hf://`
SIN bajar los 808 MB. Pensado para que el equipo trabaje en paralelo.

Exporta tablas base + materializa las vistas signadas. Escribe un README con el esquema.

Uso:
    python scripts/export_graph_parquet.py
    # luego: python scripts/hf_sync.py push --repo bpalacios/chilean-political-dataset \
    #            --path data/processed/graph_parquet --in-repo graph_parquet
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/graph.duckdb"
OUT = ROOT / "data/processed/graph_parquet"

# tablas base + vistas (se materializan a parquet)
RELATIONS = ["runs", "articles", "nodes", "aliases", "mentions", "edges",
             "node_signed_degree", "edges_by_period"]

README = """# Grafo político signado chileno (2019-2022) — tablas Parquet

Export de `graph.duckdb` (red signada de actores políticos chilenos). Una arista =
una relación `(actor → acto → actor, polaridad, tema)` extraída de noticias.

## Tablas
| archivo | filas | qué es |
|---|---|---|
| `nodes.parquet` | ~78.7k | actores canónicos (person/party/institution/coalition/movement/org). `degree`, `n_mentions`, `curated`. |
| `edges.parquet` | ~433k | relaciones signadas: `from_node_id`, `to_node_id`, `act_type`, `polarity` (positive/negative/neutral), `issue`, `evidence_quote`, `publish_date`, `period`. |
| `aliases.parquet` | ~88k | formas de superficie por nodo (`surface_form`, `surface_norm`). |
| `mentions.parquet` | ~910k | menciones NER por artículo → nodo. |
| `articles.parquet` | ~80k | artículos (id, título, body, fecha). |
| `runs.parquet` | — | trazabilidad (NER/ER/RE: modelo, genoma, params). |
| `node_signed_degree.parquet` | — | grado signado por nodo (`pos_degree`, `neg_degree`, `degree`). |
| `edges_by_period.parquet` | — | agregado por par+período (`sign_sum`, `n`). |

## Cargar
```python
import duckdb
con = duckdb.connect()
# local
edges = con.execute("SELECT * FROM 'graph_parquet/edges.parquet'").df()
# remoto desde HF (sin bajar todo), requiere httpfs + token para repo privado:
con.execute("SET hf_token='<tu_token>'")
top = con.execute('''
  SELECT n.canonical, s.pos_degree, s.neg_degree, s.degree
  FROM 'hf://datasets/bpalacios/chilean-political-dataset/graph_parquet/node_signed_degree.parquet' s
  ORDER BY degree DESC LIMIT 20''').df()
```
O con pandas: `pd.read_parquet('graph_parquet/edges.parquet')`.

## Notas
- `polarity` es la columna de signo (positive=+1, negative=-1) para la red signada.
- Filtrar `nodes.curated = TRUE` para el núcleo curado del top-grado.
- `period` = año (string) derivado de `publish_date`.
"""


def main() -> None:
    import duckdb
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET enable_progress_bar=false")
    for rel in RELATIONS:
        dst = OUT / f"{rel}.parquet"
        con.execute(f"COPY (SELECT * FROM {rel}) TO '{dst.as_posix()}' (FORMAT parquet)")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{dst.as_posix()}')").fetchone()[0]
        mb = dst.stat().st_size / 1e6
        print(f"  {rel:22s} {n:>10,} filas  {mb:7.1f} MB", flush=True)
    con.close()
    (OUT / "README.md").write_text(README, encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.glob("*.parquet")) / 1e6
    print(f"\n✓ {OUT.relative_to(ROOT)} ({total:.0f} MB total) + README.md")


if __name__ == "__main__":
    main()
