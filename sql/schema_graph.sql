-- ============================================================================
-- graph.duckdb — esquema del grafo de relaciones políticas signadas
-- DuckDB. Idempotente (DROP IF EXISTS). Determinístico: el LLM solo cura nodos
-- del top por grado; los IDs y la estructura son deterministas.
-- Ejecutar: python -m text2sg.graph_db --init   (o duckdb graph.duckdb < sql/schema_graph.sql)
-- ============================================================================

DROP VIEW   IF EXISTS edges_by_period;
DROP VIEW   IF EXISTS node_signed_degree;
DROP TABLE  IF EXISTS edges;
DROP TABLE  IF EXISTS mentions;
DROP TABLE  IF EXISTS aliases;
DROP TABLE  IF EXISTS nodes;
DROP TABLE  IF EXISTS articles;
DROP TABLE  IF EXISTS runs;
DROP SEQUENCE IF EXISTS seq_alias;
DROP SEQUENCE IF EXISTS seq_mention;
DROP SEQUENCE IF EXISTS seq_edge;

CREATE SEQUENCE seq_alias   START 1;
CREATE SEQUENCE seq_mention START 1;
CREATE SEQUENCE seq_edge    START 1;

-- ---------------------------------------------------------------------------
-- runs — trazabilidad: cada corrida NER/ER/RE con su modelo, genoma y prompt.
-- Centraliza el "qué versión produjo qué" (FK desde mentions y edges).
-- ---------------------------------------------------------------------------
CREATE TABLE runs (
  run_id       VARCHAR PRIMARY KEY,      -- 're-20260619-haikuGE', 'ner-20260619-gliner'
  kind         VARCHAR NOT NULL,         -- 'ner' | 'er' | 're'
  model        VARCHAR,                  -- 'urchade/gliner_multi-v2.1' | 'claude-haiku-4-5' | 'gemini-2.5-flash'
  genome_id    VARCHAR,                  -- 'id15' | 'haiku_ge_best'
  genome_hash  VARCHAR,                  -- hash del genoma usado
  prompt_id    VARCHAR,                  -- id del prompt
  prompt_hash  VARCHAR,                  -- hash del prompt
  params       VARCHAR,                  -- JSON: {threshold, group, fuzzy_cutoff, ...}
  n_items      INTEGER,                  -- artículos/relaciones procesados
  created_at   TIMESTAMP,
  notes        VARCHAR
);

-- ---------------------------------------------------------------------------
-- articles — la noticia: body, título, origen, fecha, período.
-- ---------------------------------------------------------------------------
CREATE TABLE articles (
  article_id   VARCHAR PRIMARY KEY,      -- md5(body)
  title        VARCHAR,
  body         VARCHAR,                  -- texto completo (auditoría/autocontención)
  body_tokens  INTEGER,
  source       VARCHAR,                  -- medio
  publish_date DATE,
  year         INTEGER,
  period       VARCHAR                   -- 'YYYY-H1' | 'YYYY-H2'
);

-- ---------------------------------------------------------------------------
-- nodes — actores canónicos (el diccionario de entidades).
-- ---------------------------------------------------------------------------
CREATE TABLE nodes (
  node_id      VARCHAR PRIMARY KEY,      -- 'POL-00042' estable
  canonical    VARCHAR NOT NULL,
  node_type    VARCHAR NOT NULL,         -- person|party|institution|coalition|movement|org
  role         VARCHAR,
  n_mentions   INTEGER DEFAULT 0,
  n_articles   INTEGER DEFAULT 0,
  degree       INTEGER DEFAULT 0,        -- pre-computado (ranking / curación top)
  first_seen   DATE,
  last_seen    DATE,
  curated      BOOLEAN DEFAULT FALSE,    -- TRUE si lo curó Sonnet/humano
  confidence   DOUBLE  DEFAULT 1.0
);

-- ---------------------------------------------------------------------------
-- aliases — surface forms por nodo (1:N). UNIQUE(surface_norm) = anti-duplicación.
-- ---------------------------------------------------------------------------
CREATE TABLE aliases (
  alias_id     BIGINT PRIMARY KEY DEFAULT nextval('seq_alias'),
  node_id      VARCHAR NOT NULL REFERENCES nodes(node_id),
  surface_form VARCHAR NOT NULL,
  surface_norm VARCHAR NOT NULL,
  source       VARCHAR,                  -- gazetteer|ner|sigla|manual
  n_occurrences INTEGER DEFAULT 0,
  UNIQUE (surface_norm)                  -- un surface normalizado → un solo nodo
);

-- ---------------------------------------------------------------------------
-- mentions — cada aparición NER en un artículo (puente + auditoría).
-- ---------------------------------------------------------------------------
CREATE TABLE mentions (
  mention_id   BIGINT PRIMARY KEY DEFAULT nextval('seq_mention'),
  node_id      VARCHAR REFERENCES nodes(node_id),
  article_id   VARCHAR NOT NULL REFERENCES articles(article_id),
  run_id       VARCHAR REFERENCES runs(run_id),    -- qué corrida NER la produjo
  surface_form VARCHAR NOT NULL,
  char_start   INTEGER,
  char_end     INTEGER,
  ner_score    DOUBLE,
  resolved_by  VARCHAR,                  -- exact|fuzzy|splink|llm|sigla
  match_score  DOUBLE
);

-- ---------------------------------------------------------------------------
-- edges — relaciones signadas (el grafo). UNIQUE evita duplicados; run_id versiona.
-- ---------------------------------------------------------------------------
CREATE TABLE edges (
  edge_id      BIGINT PRIMARY KEY DEFAULT nextval('seq_edge'),
  from_node_id VARCHAR NOT NULL REFERENCES nodes(node_id),
  to_node_id   VARCHAR NOT NULL REFERENCES nodes(node_id),
  article_id   VARCHAR NOT NULL REFERENCES articles(article_id),
  run_id       VARCHAR REFERENCES runs(run_id),    -- qué corrida RE la produjo
  act_type     VARCHAR NOT NULL,         -- 9 tipos
  polarity     VARCHAR NOT NULL,         -- positive|negative|neutral
  issue        VARCHAR,
  evidence_quote VARCHAR NOT NULL,
  confidence   DOUBLE,
  publish_date DATE,                     -- denormalizado (query temporal rápida)
  period       VARCHAR,                  -- denormalizado
  UNIQUE (from_node_id, to_node_id, article_id, act_type, run_id)  -- idempotencia
);

-- ---------------------------------------------------------------------------
-- Índices para las consultas frecuentes.
-- ---------------------------------------------------------------------------
CREATE INDEX idx_alias_norm   ON aliases(surface_norm);
CREATE INDEX idx_alias_node   ON aliases(node_id);
CREATE INDEX idx_ment_node    ON mentions(node_id);
CREATE INDEX idx_ment_article ON mentions(article_id);
CREATE INDEX idx_edge_from    ON edges(from_node_id);
CREATE INDEX idx_edge_to      ON edges(to_node_id);
CREATE INDEX idx_edge_period  ON edges(period);

-- ---------------------------------------------------------------------------
-- Vistas analíticas.
-- ---------------------------------------------------------------------------
CREATE VIEW node_signed_degree AS
SELECT n.node_id, n.canonical, n.node_type,
       SUM(CASE WHEN e.polarity='positive' THEN 1 ELSE 0 END) AS pos_degree,
       SUM(CASE WHEN e.polarity='negative' THEN 1 ELSE 0 END) AS neg_degree,
       COUNT(*) AS degree
FROM nodes n
JOIN edges e ON n.node_id IN (e.from_node_id, e.to_node_id)
GROUP BY 1, 2, 3;

CREATE VIEW edges_by_period AS
SELECT from_node_id, to_node_id, period,
       SUM(CASE WHEN polarity='positive' THEN 1
                WHEN polarity='negative' THEN -1 ELSE 0 END) AS sign_sum,
       COUNT(*) AS n
FROM edges
GROUP BY 1, 2, 3;
