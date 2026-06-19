"""Crea e inicializa graph.duckdb desde sql/schema_graph.sql.

El esquema (runs, articles, nodes, aliases, mentions, edges) está en SQL puro para que
sea legible y ejecutable también con el CLI de duckdb. Este módulo lo aplica y expone
helpers de conexión.

Uso:
    python -m text2sg.graph_db --init                 # crea data/processed/graph.duckdb
    python -m text2sg.graph_db --init --db otro.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "sql" / "schema_graph.sql"
DEFAULT_DB = ROOT / "data" / "processed" / "graph.duckdb"


def init_db(db_path: Path | str = DEFAULT_DB, schema_path: Path | str = SCHEMA):
    """Crea (o reinicia) la base aplicando el DDL. Devuelve la conexión DuckDB."""
    import duckdb

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(Path(schema_path).read_text(encoding="utf-8"))
    return con


def tables(con) -> list[str]:
    """Lista las tablas/vistas creadas."""
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name").fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="crear/reiniciar la base")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    if args.init:
        con = init_db(args.db)
        print(f"graph.duckdb inicializada en {args.db}")
        print("objetos:", ", ".join(tables(con)))


if __name__ == "__main__":
    main()
