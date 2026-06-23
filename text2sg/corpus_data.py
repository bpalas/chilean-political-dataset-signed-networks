"""Ingesta del corpus REAL de noticias a un lago Parquet particionado por año, y
loaders para alimentar el extractor a escala. Sin LLM, $0.

El corpus (`edgelist_grande_full.csv`, ~2 GB) trae la extracción VIEJA (una fila por
par de actores), así que hay ~5 filas por artículo. Dedup por `news_index` deja 1 fila
por artículo (~2.1M únicos). DuckDB lee el CSV por streaming → no carga 2 GB en RAM.

Encoding: el CSV es UTF-8 válido y limpio (verificado por ordinales: `\\xc3\\xa1`→á, sin
U+FFFD). NO se aplica reparación de encoding — dañaría texto ya correcto. Solo se lee y
escribe en UTF-8.

Uso:
    from text2sg.corpus_data import build_corpus_parquet, load_corpus_articles, corpus_stats
    build_corpus_parquet(CSV, "results/corpus/raw/articles")          # una vez (~minutos)
    df = load_corpus_articles("results/corpus/raw/articles",          # filtrar + muestrear
                              year_range=(2019, 2026),
                              tema_whitelist=["acusación constitucional", ...],
                              limit=80_000)
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import pandas as pd

# Clave de artículo = CONTENIDO. `news_index` NO es único (se reusa: ~16k valores que
# reinician), así que el id estable es `md5(body)` (content-addressed → idempotente entre
# re-ingestas). Las columnas a nivel de relación (from_node_*, sentiment, ...) NO entran al
# lago: se re-extraen. `news_index` se conserva como columna para joinear con la extracción vieja.
ARTICLE_SELECT = (
    "md5(body) AS article_id, "
    "news_index, "
    "try_cast(publish_date AS DATE) AS publish_date, "
    "coalesce(extract(year FROM try_cast(publish_date AS DATE)), 0)::INT AS year, "
    "title, body, tema_local"
)


def _sql_str(p: Path | str) -> str:
    """Path → literal SQL seguro (forward slashes, comillas escapadas)."""
    return "'" + str(p).replace("\\", "/").replace("'", "''") + "'"


def _glob(parquet_root: Path | str) -> str:
    return str(Path(parquet_root) / "**" / "*.parquet").replace("\\", "/")


# SELECT para el corpus GRANDE de producción (Downloads/data/raw/articles_*.parquet):
# esquema id, title, body, source, country, publish_date, year. Sin tema_local (sin etiquetas
# de tópico → el pre-filtro político va por gazetteer/léxico, ver build_gazetteer/filtro).
NEWS_SELECT = (
    "md5(body) AS article_id, "
    "id AS src_id, source, "
    "try_cast(publish_date AS DATE) AS publish_date, "
    "coalesce(try_cast(year AS INT), extract(year FROM try_cast(publish_date AS DATE)), 0)::INT AS year, "
    "title, body"
)


def _build_parquet_lake(out_root: Path, con, select_sql: str, from_sql: str) -> dict:
    """Núcleo compartido: dedup por `body` (article_id = md5(body)), partición por `year`.
    Idempotente (limpia out_root). DuckDB hace streaming → no carga la fuente en RAM."""
    out_root = Path(out_root)
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
          SELECT {select_sql}
          FROM {from_sql}
          WHERE body IS NOT NULL AND length(trim(body)) > 0
          QUALIFY row_number() OVER (PARTITION BY body ORDER BY body) = 1
        ) TO {_sql_str(out_root)} (FORMAT parquet, PARTITION_BY (year));
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet({_sql_str(_glob(out_root))})"
    ).fetchone()[0]
    return {"n_articles": int(n), "out_root": str(out_root)}


def build_corpus_parquet(
    csv_path: Path | str,
    out_root: Path | str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Corpus ETIQUETADO de clivaje (CSV con tema_local + extracción vieja → gold/gazetteer).
    Una pasada CSV → Parquet particionado por `year`, dedup por contenido."""
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    from_sql = (
        f"read_csv_auto({_sql_str(csv_path)}, sample_size=-1, ignore_errors=true)"
    )
    return _build_parquet_lake(Path(out_root), con, ARTICLE_SELECT, from_sql)


def build_news_corpus_parquet(
    src_glob: Path | str,
    out_root: Path | str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Corpus GRANDE de producción (~4.88M art chilenos, parquet ya particionado).
    Dedup por contenido → lago canónico con article_id estable (md5 body)."""
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    from_sql = f"read_parquet({_sql_str(src_glob)})"
    return _build_parquet_lake(Path(out_root), con, NEWS_SELECT, from_sql)


def corpus_stats(
    parquet_root: Path | str,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    top_temas: int = 50,
) -> dict:
    """Resumen del lago para decidir el pre-filtro: conteo por año y top tópicos."""
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    glob = _sql_str(_glob(parquet_root))
    cols = {c[0] for c in con.execute(
        f"SELECT * FROM read_parquet({glob}, hive_partitioning=true) LIMIT 0").description}
    by_year = con.execute(
        f"SELECT year, count(*) n FROM read_parquet({glob}, hive_partitioning=true) "
        f"GROUP BY year ORDER BY year"
    ).fetchall()
    total = con.execute(f"SELECT count(*) FROM read_parquet({glob})").fetchone()[0]
    out = {
        "total": int(total),
        "by_year": [{"year": int(y), "n": int(n)} for y, n in by_year],
    }
    # tópico: tema_local (clivaje) o source (corpus grande) según lo que exista
    dim = "tema_local" if "tema_local" in cols else ("source" if "source" in cols else None)
    if dim:
        rows = con.execute(
            f"SELECT {dim}, count(*) n FROM read_parquet({glob}) "
            f"WHERE {dim} IS NOT NULL GROUP BY {dim} ORDER BY n DESC LIMIT {int(top_temas)}"
        ).fetchall()
        out[f"top_{dim}"] = [{dim: t, "n": int(n)} for t, n in rows]
    return out


def load_corpus_articles(
    parquet_root: Path | str,
    *,
    year_range: tuple[int, int] | None = None,
    tema_whitelist: list[str] | None = None,
    limit: int | None = None,
    seed: int = 42,
    con: duckdb.DuckDBPyConnection | None = None,
) -> pd.DataFrame:
    """Carga artículos del lago con pre-filtro (año, tópico) y muestreo reproducible.

    Devuelve un DataFrame con `article_id`, `body`, `publish_date`, `title`, `tema_local`,
    mismo shape mínimo (`article_id`, `body`) que consume `run_extraction`.

    El muestreo (cuando hay `limit`) es reproducible: `ORDER BY hash(article_id || seed)`.
    """
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    glob = _sql_str(_glob(parquet_root))
    cols = {c[0] for c in con.execute(
        f"SELECT * FROM read_parquet({glob}, hive_partitioning=true) LIMIT 0").description}
    where, params = [], []
    if year_range is not None:
        where.append("year BETWEEN ? AND ?")
        params += [int(year_range[0]), int(year_range[1])]
    if tema_whitelist:
        if "tema_local" not in cols:
            raise ValueError("tema_whitelist requiere columna 'tema_local' (corpus etiquetado); "
                             "el corpus grande no la tiene — usá el filtro político por gazetteer/léxico")
        where.append(f"tema_local IN ({','.join('?' * len(tema_whitelist))})")
        params += list(tema_whitelist)

    # SELECT * → devuelve las columnas que tenga el lago (article_id+body siempre presentes)
    sql = f"SELECT * FROM read_parquet({glob}, hive_partitioning=true)"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if limit is not None:
        # hash reproducible (depende de article_id + seed), no Random() → re-corridas idénticas.
        sql += f" ORDER BY hash(article_id || '{int(seed)}') LIMIT {int(limit)}"

    return con.execute(sql, params).fetch_df()


# ── Pre-filtro POLÍTICO (gazetteer + léxico) para el corpus grande sin tema_local ──── #

def build_gazetteer(
    clivaje_csv: Path | str,
    *,
    top_n: int = 300,
    min_len: int = 4,
    out_path: Path | str | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> list[str]:
    """Gazetteer de actores políticos desde la extracción VIEJA de clivaje
    (`from_node_label` + `to_node_label`, ya son actores nombrados). Ranking por
    frecuencia → los top_n son el núcleo político. Semilla GRATIS también para la
    entity resolution. Persiste a `out_path` (JSON) si se da. Nombres en minúscula.
    """
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    src = _sql_str(clivaje_csv)
    q = f"""
        WITH labels AS (
          SELECT lower(trim(from_node_label)) AS name
          FROM read_csv_auto({src}, sample_size=-1, ignore_errors=true)
          WHERE from_node_label IS NOT NULL AND length(trim(from_node_label)) >= {int(min_len)}
          UNION ALL
          SELECT lower(trim(to_node_label)) AS name
          FROM read_csv_auto({src}, sample_size=-1, ignore_errors=true)
          WHERE to_node_label IS NOT NULL AND length(trim(to_node_label)) >= {int(min_len)}
        )
        SELECT name FROM labels GROUP BY name ORDER BY count(*) DESC LIMIT {int(top_n)}
    """
    names = [r[0] for r in con.execute(q).fetchall()]
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
    return names


def _actor_regex(names: list[str]) -> str:
    """Alternación regex (escapada) de nombres de actor para regexp_extract_all."""
    return "(" + "|".join(re.escape(n) for n in names) + ")"


# ── Léxico político curado (chileno, minúscula) ────────────────────────── #
# Complementa el gazetteer: captura artículos políticos que NO nombran a los
# top-300 actores por nombre pero sí mencionan roles, instituciones o procesos.
_POLITICAL_LEXICON: list[str] = [
    # roles
    "ministro", "ministra", "diputado", "diputada", "senador", "senadora",
    "presidente", "presidenta", "vicepresidente", "gobernador", "gobernadora",
    "alcalde", "alcaldesa", "concejal", "subsecretario", "subsecretaria",
    "intendente", "seremi", "secretario de estado",
    # instituciones
    "senado", "cámara de diputados", "congreso nacional", "congreso",
    "tribunal constitucional", "contraloría", "banco central",
    "palacio de la moneda", "la moneda", "gobierno de chile",
    "ministerio de hacienda", "ministerio del interior",
    # partidos y coaliciones
    "udi", "renovación nacional", "partido socialista", "partido comunista",
    "frente amplio", "democracia cristiana", "evópoli", "partido republicano",
    "apruebo dignidad", "la concertación", "nueva mayoría", "chile vamos",
    # procesos electorales y constitucionales
    "plebiscito", "elecciones presidenciales", "elección presidencial",
    "segunda vuelta", "campaña presidencial", "constitución política",
    "convención constitucional", "proceso constituyente",
    # actos legislativos y parlamentarios
    "acusación constitucional", "interpelación", "proyecto de ley",
    "moción parlamentaria", "veto presidencial", "votación en sala",
    "comisión de hacienda", "comisión mixta",
    # términos de clivaje político
    "estallido social", "18 de octubre", "reforma tributaria",
    "reforma de pensiones", "apruebo", "rechazo",
    # segundo ciclo constitucional + actores institucionales 2023-2026
    "consejo constitucional", "comisión experta", "consejero constitucional",
    "consejera constitucional", "anteproyecto constitucional", "partido de la gente",
    "partido republicano", "amarillos por chile", "servel", "ministerio de seguridad pública",
    # era 2014-2018 (Bachelet II / Piñera II): coaliciones y procesos del período
    "nueva mayoría", "concertación", "reforma educacional", "gratuidad",
    "asamblea constituyente", "proceso constituyente",
]


def build_political_lexicon(
    extra: list[str] | None = None,
    *,
    out_path: Path | str | None = None,
) -> list[str]:
    """Léxico político curado (chileno, minúscula) que complementa el gazetteer.

    Cubre roles (ministro, diputado, senador...), instituciones (senado, congreso,
    la moneda...), partidos (udi, ps, frente amplio...) y procesos (plebiscito,
    acusación constitucional...). Útil para artículos que no nombran a los
    top-300 actores por nombre.

    `extra` permite inyectar términos adicionales (se normalizan a minúscula y se
    deduplan). Si `out_path` se da, persiste el léxico como JSON.
    """
    terms = list(_POLITICAL_LEXICON)
    if extra:
        seen = set(terms)
        for t in extra:
            nt = t.lower().strip()
            if nt and nt not in seen:
                terms.append(nt)
                seen.add(nt)
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return terms


def load_political_articles(
    parquet_root: Path | str,
    gazetteer: list[str],
    *,
    year_range: tuple[int, int] | None = None,
    min_actors: int = 2,
    lexicon: list[str] | None = None,
    min_lexicon_hits: int = 3,
    limit: int | None = None,
    seed: int = 42,
    con: duckdb.DuckDBPyConnection | None = None,
) -> pd.DataFrame:
    """Selecciona artículos POLÍTICOS del lago grande (OR amplio).

    Condición de inclusión:
        (matched_actors ≥ min_actors)                             -- gazetteer
        OR (len(lexicon) > 0 AND matched_lexicon ≥ min_lexicon_hits)  -- léxico

    Sin `lexicon` el comportamiento es idéntico al anterior (solo gazetteer).

    Devuelve las columnas del lago + `matched_actors` (lista) y, si se pasa
    `lexicon`, también `matched_lexicon` (lista). Muestreo reproducible por
    hash(article_id||seed).
    """
    con = con or duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    glob = _sql_str(_glob(parquet_root))
    rx_actors = _actor_regex(gazetteer)

    if lexicon:
        rx_lex = _actor_regex(lexicon)
        # params: rx_actors, rx_lex, min_actors, min_lexicon_hits
        params: list = [rx_actors, rx_lex, int(min_actors), int(min_lexicon_hits)]
        base_where = "(len(matched_actors) >= ? OR len(matched_lexicon) >= ?)"
        year_params: list = []
        if year_range is not None:
            base_where += " AND year BETWEEN ? AND ?"
            year_params = [int(year_range[0]), int(year_range[1])]
        sql = (
            f"WITH m AS (SELECT *, "
            f"list_distinct(regexp_extract_all(lower(title || ' ' || body), ?)) AS matched_actors, "
            f"list_distinct(regexp_extract_all(lower(title || ' ' || body), ?)) AS matched_lexicon "
            f"FROM read_parquet({glob}, hive_partitioning=true)) "
            f"SELECT * FROM m WHERE {base_where}"
        )
        params += year_params
    else:
        params = [rx_actors, int(min_actors)]
        year_params = []
        if year_range is not None:
            year_params = [int(year_range[0]), int(year_range[1])]
        sql = (
            f"WITH m AS (SELECT *, "
            f"list_distinct(regexp_extract_all(lower(title || ' ' || body), ?)) AS matched_actors "
            f"FROM read_parquet({glob}, hive_partitioning=true)) "
            f"SELECT * FROM m WHERE len(matched_actors) >= ?"
            + (" AND year BETWEEN ? AND ?" if year_range else "")
        )
        params += year_params

    if limit is not None:
        sql += f" ORDER BY hash(article_id || '{int(seed)}') LIMIT {int(limit)}"
    return con.execute(sql, params).fetch_df()
