"""Tests de la ingesta del corpus real (corpus_data): dedup por news_index,
particionado por año, pre-filtro y muestreo reproducible. Sin LLM, sin red."""
from pathlib import Path

import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from text2sg.corpus_data import (  # noqa: E402
    build_corpus_parquet,
    build_gazetteer,
    build_news_corpus_parquet,
    build_political_lexicon,
    corpus_stats,
    load_corpus_articles,
    load_political_articles,
)


def _make_csv(path: Path) -> None:
    """CSV mini que imita el corpus: 3 artículos, ~varias filas-relación c/u,
    en 2 años, con un acento UTF-8 para verificar que no se rompe el encoding."""
    rows = [
        # news_index, id, publish_date, title, body, tema_local
        ("A1", 0, "2019-03-01", "Título A1", "Boric acusó a Matthei.", "acusación política"),
        ("A1", 1, "2019-03-01", "Título A1", "Boric acusó a Matthei.", "acusación política"),
        ("A1", 2, "2019-03-01", "Título A1", "Boric acusó a Matthei.", "acusación política"),
        ("A2", 3, "2021-07-15", "Título A2", "Reunión de gabinete económico.", "economía"),
        ("A2", 4, "2021-07-15", "Título A2", "Reunión de gabinete económico.", "economía"),
        ("A3", 5, "2021-09-20", "Título A3", "Fútbol y farándula.", "deportes"),
    ]
    df = pd.DataFrame(rows, columns=[
        "news_index", "id", "publish_date", "title", "body", "tema_local"])
    df.to_csv(path, index=False, encoding="utf-8")


def test_build_dedups_to_unique_articles_partitioned_by_year(tmp_path):
    csv = tmp_path / "corpus.csv"
    _make_csv(csv)
    out = tmp_path / "articles"
    res = build_corpus_parquet(csv, out)

    # 6 filas-relación → 3 bodies únicos (dedup por CONTENIDO, no news_index)
    assert res["n_articles"] == 3
    # particionado por año: 2019 y 2021
    years = {p.name for p in out.glob("year=*")}
    assert years == {"year=2019", "year=2021"}
    # article_id es estable y único (hash del body)
    df = load_corpus_articles(out)
    assert df["article_id"].nunique() == 3


def test_build_preserves_utf8_accents(tmp_path):
    csv = tmp_path / "corpus.csv"
    _make_csv(csv)
    out = tmp_path / "articles"
    build_corpus_parquet(csv, out)
    df = load_corpus_articles(out)
    temas = set(df["tema_local"])
    # el acento sobrevive intacto (verificado por contenido, no por display)
    assert "acusación política" in temas
    assert any("acusó" in b for b in df["body"])


def test_load_filters_by_year_and_tema(tmp_path):
    csv = tmp_path / "corpus.csv"
    _make_csv(csv)
    out = tmp_path / "articles"
    build_corpus_parquet(csv, out)

    only_2021 = load_corpus_articles(out, year_range=(2021, 2021))
    assert set(only_2021["title"]) == {"Título A2", "Título A3"}

    econ = load_corpus_articles(out, tema_whitelist=["economía"])
    assert set(econ["title"]) == {"Título A2"}


def test_load_limit_is_reproducible(tmp_path):
    csv = tmp_path / "corpus.csv"
    _make_csv(csv)
    out = tmp_path / "articles"
    build_corpus_parquet(csv, out)

    s1 = load_corpus_articles(out, limit=2, seed=7)
    s2 = load_corpus_articles(out, limit=2, seed=7)
    assert list(s1["article_id"]) == list(s2["article_id"])  # mismo seed → misma muestra
    assert len(s1) == 2


def test_corpus_stats_reports_year_and_tema(tmp_path):
    csv = tmp_path / "corpus.csv"
    _make_csv(csv)
    out = tmp_path / "articles"
    build_corpus_parquet(csv, out)

    stats = corpus_stats(out)
    assert stats["total"] == 3
    years = {row["year"]: row["n"] for row in stats["by_year"]}
    assert years == {2019: 1, 2021: 2}
    assert any(t["tema_local"] == "economía" for t in stats["top_tema_local"])


# ── corpus GRANDE (parquet) + gazetteer + filtro político ─────────────── #

def _make_news_parquet(path: Path) -> None:
    """Parquet mini imitando el corpus grande (id, title, body, source, country,
    publish_date, year). Sin tema_local."""
    rows = [
        ("n1", "Boric y Kast", "Boric debatió con Kast sobre seguridad.", "biobiochile.cl", "Chile", "2021-11-01", 2021),
        ("n2", "Solo Boric", "Boric anunció una medida económica.", "latercera.com", "Chile", "2021-05-01", 2021),
        ("n3", "Fútbol", "Colo-Colo ganó el clásico ayer.", "t13.cl", "Chile", "2021-03-01", 2021),
        ("n4", "Bachelet y Piñera", "Bachelet criticó a Piñera por la gestión.", "emol.com", "Chile", "2019-08-01", 2019),
    ]
    df = pd.DataFrame(rows, columns=[
        "id", "title", "body", "source", "country", "publish_date", "year"])
    df.to_parquet(path, index=False)


def test_build_news_corpus_dedups_and_keeps_source(tmp_path):
    src = tmp_path / "news.parquet"
    _make_news_parquet(src)
    out = tmp_path / "news_lake"
    res = build_news_corpus_parquet(src, out)
    assert res["n_articles"] == 4
    df = load_corpus_articles(out)
    assert "source" in df.columns and "tema_local" not in df.columns


def test_build_gazetteer_ranks_actors_by_frequency(tmp_path):
    csv = tmp_path / "corpus.csv"
    # CSV con columnas de la extracción vieja (from_node_label/to_node_label)
    pd.DataFrame([
        {"news_index": "A1", "id": 0, "publish_date": "2021-01-01", "title": "t", "body": "b",
         "from_node_label": "Gabriel Boric", "to_node_label": "José Antonio Kast", "tema_local": "x"},
        {"news_index": "A2", "id": 1, "publish_date": "2021-01-02", "title": "t", "body": "b",
         "from_node_label": "Gabriel Boric", "to_node_label": "Evelyn Matthei", "tema_local": "x"},
    ]).to_csv(csv, index=False, encoding="utf-8")
    gaz = build_gazetteer(csv, top_n=10, out_path=tmp_path / "gaz.json")
    assert gaz[0] == "gabriel boric"          # el más frecuente primero
    assert "josé antonio kast" in gaz and "evelyn matthei" in gaz
    assert (tmp_path / "gaz.json").exists()


def test_load_political_articles_filters_by_min_actors(tmp_path):
    src = tmp_path / "news.parquet"
    _make_news_parquet(src)
    out = tmp_path / "news_lake"
    build_news_corpus_parquet(src, out)
    gaz = ["boric", "kast", "bachelet", "piñera", "matthei"]

    # min_actors=2 → solo n1 (Boric+Kast) y n4 (Bachelet+Piñera); n2 (solo Boric) y n3 (fútbol) fuera
    pol = load_political_articles(out, gaz, min_actors=2)
    assert set(pol["title"]) == {"Boric y Kast", "Bachelet y Piñera"}

    # filtro por año dentro del subconjunto político
    pol2021 = load_political_articles(out, gaz, min_actors=2, year_range=(2021, 2021))
    assert set(pol2021["title"]) == {"Boric y Kast"}

    # min_actors=1 amplía a los que mencionan ≥1 actor (incluye n2 "solo Boric")
    pol1 = load_political_articles(out, gaz, min_actors=1)
    assert "Solo Boric" in set(pol1["title"])
    assert "Fútbol" not in set(pol1["title"])


# ── Léxico político + OR amplio ─────────────────────────────────────────── #

def test_build_political_lexicon_defaults(tmp_path):
    lex = build_political_lexicon()
    assert isinstance(lex, list)
    assert len(lex) >= 40
    assert all(isinstance(t, str) and t == t.lower() for t in lex)
    # términos clave presentes
    assert "ministro" in lex
    assert "senado" in lex
    assert "plebiscito" in lex


def test_build_political_lexicon_extra_and_persist(tmp_path):
    lex = build_political_lexicon(
        extra=["Reform Tributaria", "PLEBISCITO"],  # mayúsculas → deben normalizarse
        out_path=tmp_path / "lex.json",
    )
    assert "reform tributaria" in lex
    # dedup: plebiscito ya existía, no se duplica
    assert lex.count("plebiscito") == 1
    assert (tmp_path / "lex.json").exists()


def _make_news_for_lexicon(path: Path) -> None:
    """Parquet con artículos para testear OR gazetteer + léxico."""
    rows = [
        # n1: ≥2 actores (gazetteer) → incluido por gazetteer
        ("n1", "Boric y Kast", "Boric debatió con Kast sobre seguridad.", "biobio", "Chile", "2021-11-01", 2021),
        # n2: 1 actor + léxico insuficiente (2 hits) → excluido (OR falla)
        ("n2", "Solo Boric y el senado", "Boric habló en el senado.", "latercera", "Chile", "2021-05-01", 2021),
        # n3: 0 actores + léxico abundante (≥3 hits) → incluido por léxico
        ("n3", "Sesión del congreso", "El senado y la cámara de diputados debatieron el plebiscito.", "emol", "Chile", "2020-09-01", 2020),
        # n4: fútbol puro → excluido
        ("n4", "Fútbol", "Colo-Colo ganó ayer.", "t13", "Chile", "2021-03-01", 2021),
    ]
    import pandas as pd
    pd.DataFrame(rows, columns=[
        "id", "title", "body", "source", "country", "publish_date", "year"]
    ).to_parquet(path, index=False)


def test_load_political_articles_or_lexicon(tmp_path):
    src = tmp_path / "news.parquet"
    _make_news_for_lexicon(src)
    out = tmp_path / "news_lake"
    build_news_corpus_parquet(src, out)
    gaz = ["boric", "kast", "bachelet", "piñera"]
    lex = build_political_lexicon()

    # OR amplio: ≥2 actores OR ≥3 léxico
    pol = load_political_articles(out, gaz, min_actors=2, lexicon=lex, min_lexicon_hits=3)
    titles = set(pol["title"])
    assert "Boric y Kast" in titles        # gazetteer
    assert "Sesión del congreso" in titles  # léxico (senado + cámara de diputados + plebiscito = 3)
    assert "Fútbol" not in titles
    assert "matched_lexicon" in pol.columns

    # sin léxico (comportamiento anterior): "Sesión del congreso" no entra
    pol_no_lex = load_political_articles(out, gaz, min_actors=2)
    assert "Sesión del congreso" not in set(pol_no_lex["title"])
    assert "matched_lexicon" not in pol_no_lex.columns


def test_load_political_articles_or_lexicon_with_year_filter(tmp_path):
    src = tmp_path / "news.parquet"
    _make_news_for_lexicon(src)
    out = tmp_path / "news_lake"
    build_news_corpus_parquet(src, out)
    gaz = ["boric", "kast"]
    lex = build_political_lexicon()

    # año 2021: "Sesión del congreso" es 2020 → queda fuera
    pol = load_political_articles(
        out, gaz, min_actors=2, lexicon=lex, min_lexicon_hits=3, year_range=(2021, 2021)
    )
    titles = set(pol["title"])
    assert "Boric y Kast" in titles
    assert "Sesión del congreso" not in titles
