# Diseño del grafo — `graph.duckdb`

> Esquema de la base del grafo de relaciones políticas signadas. DuckDB + Parquet
> (decisión LOCKED, doc 04). Diseño determinístico; el modelo (Sonnet) solo cura el
> top por grado, no decide la estructura.

## 1. Requisitos

**Funcionales**
- Guardar **actores canónicos** (nodos) con su **diccionario de aliases** (publicable).
- Guardar **relaciones signadas** (aristas) con evidencia textual y metadata temporal.
- Trazar cada arista a la **versión** que la produjo (genoma/modelo) → comparar corridas.
- Soportar **análisis longitudinal** (por semestre) y de **red signada** (grado +/−).
- Auditar: de un nodo → sus menciones → el artículo y la cita.

**No funcionales**
- Escala: 80k → 383k → 4.88M artículos; ~10⁶–10⁷ aristas.
- $0, sin servidor (embebido). Idempotente y re-ejecutable. Incremental (news diario).
- Determinístico: misma entrada → mismo grafo. El LLM solo cura, no genera IDs.

## 2. Diseño de alto nivel

```
  runs ──┬──< mentions >──┐
         └──< edges >─────┤
                       nodes ──< aliases
  articles ──< mentions
  articles ──< edges          (from_node_id, to_node_id)

  runs     = trazabilidad: modelo + genoma + prompt de cada corrida
  nodes    = actores canónicos (el diccionario)
  aliases  = surface forms por nodo (1:N)        ← "guardar los aliases"
  mentions = cada aparición NER en un artículo   ← puente auditoría
  edges    = relaciones signadas (RE)            ← las aristas del grafo
  articles = la noticia: body, título, medio, fecha, período
```

> **DDL canónico:** [`sql/schema_graph.sql`](../sql/schema_graph.sql) (ejecutable en DuckDB).
> Crear: `python -m text2sg.graph_db --init`. Lo de abajo es el resumen comentado.

## 3. Esquema (resumen — DDL completo en `sql/schema_graph.sql`)

```sql
-- Trazabilidad: cada corrida NER/ER/RE con su modelo, genoma y prompt.
-- mentions.run_id y edges.run_id apuntan acá → "qué versión produjo qué".
CREATE TABLE runs (
  run_id      VARCHAR PRIMARY KEY,          -- 're-20260619-haikuGE'
  kind        VARCHAR,                       -- ner | er | re
  model       VARCHAR,                       -- gliner_multi-v2.1 | claude-haiku-4-5 | gemini-2.5-flash
  genome_id   VARCHAR,  genome_hash VARCHAR, -- id15 | haiku_ge_best
  prompt_id   VARCHAR,  prompt_hash VARCHAR,
  params      VARCHAR,                        -- JSON (threshold, group, ...)
  n_items     INTEGER,  created_at TIMESTAMP, notes VARCHAR
);

-- La noticia completa (auditoría / autocontención).
CREATE TABLE articles (
  article_id   VARCHAR PRIMARY KEY,        -- md5(body)
  title        VARCHAR,
  body         VARCHAR,                     -- texto completo
  body_tokens  INTEGER,
  source       VARCHAR,                     -- medio
  publish_date DATE,
  year         INTEGER,
  period       VARCHAR                       -- 'YYYY-H1' / 'YYYY-H2'
);

-- Nodos = actores canónicos (el diccionario de entidades)
CREATE TABLE nodes (
  node_id      VARCHAR PRIMARY KEY,         -- 'POL-00042' estable (idempotente)
  canonical    VARCHAR NOT NULL,
  node_type    VARCHAR NOT NULL,            -- person|party|institution|coalition|movement|org
  role         VARCHAR,                     -- cargo (nullable)
  n_mentions   INTEGER DEFAULT 0,
  n_articles   INTEGER DEFAULT 0,
  degree       INTEGER DEFAULT 0,           -- pre-computado para ranking
  first_seen   DATE,
  last_seen    DATE,
  curated      BOOLEAN DEFAULT FALSE,       -- TRUE si lo curó Sonnet/humano
  confidence   DOUBLE DEFAULT 1.0
);

-- Aliases = surface forms por nodo (1 nodo : N aliases)
CREATE TABLE aliases (
  alias_id     BIGINT PRIMARY KEY,
  node_id      VARCHAR NOT NULL REFERENCES nodes(node_id),
  surface_form VARCHAR NOT NULL,
  surface_norm VARCHAR NOT NULL,            -- normalizado (lower, sin acentos)
  source       VARCHAR,                     -- gazetteer|ner|sigla|manual
  n_occurrences INTEGER DEFAULT 0,
  UNIQUE (surface_norm)                     -- un surface normalizado → un solo nodo
);

-- Menciones = cada aparición NER en un artículo (puente + auditoría)
CREATE TABLE mentions (
  mention_id   BIGINT PRIMARY KEY,
  node_id      VARCHAR REFERENCES nodes(node_id),
  article_id   VARCHAR NOT NULL REFERENCES articles(article_id),
  run_id       VARCHAR REFERENCES runs(run_id),    -- qué corrida NER
  surface_form VARCHAR NOT NULL,
  char_start   INTEGER,                     -- del NER (GLiNER) → auditar
  char_end     INTEGER,
  ner_score    DOUBLE,
  resolved_by  VARCHAR,                     -- exact|fuzzy|splink|llm|sigla
  match_score  DOUBLE
);

-- Aristas = relaciones signadas (el grafo). run_id → toda la trazabilidad (en runs).
CREATE TABLE edges (
  edge_id      BIGINT PRIMARY KEY,
  from_node_id VARCHAR NOT NULL REFERENCES nodes(node_id),
  to_node_id   VARCHAR NOT NULL REFERENCES nodes(node_id),
  article_id   VARCHAR NOT NULL REFERENCES articles(article_id),
  run_id       VARCHAR REFERENCES runs(run_id),    -- qué corrida RE (modelo/genoma/prompt)
  act_type     VARCHAR NOT NULL,            -- 9 tipos
  polarity     VARCHAR NOT NULL,            -- positive|negative|neutral
  issue        VARCHAR,
  evidence_quote VARCHAR NOT NULL,
  confidence   DOUBLE,
  publish_date DATE,                        -- denormalizado (query temporal rápida)
  period       VARCHAR,                     -- denormalizado
  UNIQUE (from_node_id, to_node_id, article_id, act_type, run_id)  -- idempotencia
);
```

**Por qué estas decisiones**
- **`aliases` como tabla** (no JSON en nodes): queryable, con FK, `UNIQUE(surface_norm)` garantiza que un surface no se asigne a dos nodos → **anti-duplicación por construcción**.
- **`UNIQUE` en edges**: re-correr el pipeline no duplica aristas; cambiar de genoma crea versión nueva (no pisa).
- **Denormalizar `publish_date`/`period` en edges**: los análisis temporales (cortes semestrales) son el caso de uso central → evitar el join a `articles` en cada query.
- **`degree`/`n_mentions` pre-computados**: ranking de actores (top grado) sin recomputar — justo lo que necesita la curación con Sonnet.
- **`curated` + `genome_hash`/`model`**: separar lo automático de lo curado, y versionar.

## 4. Flujo determinístico de poblado

```
1. NER (GLiNER)         → mentions_raw.parquet      (surface, tipo, span, score)   [det.]
2. ER determinístico    → resolution + nodes + aliases                            [det.]
     normalización exacta → blocking (tipo × apellido) → fuzzy + guardas
3. Curación (Sonnet)    → merge top-N por grado, siglas, canonical                [LLM, acotado]
     marca curated=TRUE; corrige solo el núcleo de alto grado
4. RE → edges           → mapear from/to a node_id vía aliases.surface_norm       [det.]
5. LOAD a graph.duckdb  → con PK/FK; UNIQUE evita duplicados
```

El LLM entra **solo en el paso 3** (curar el top), sobre IDs ya asignados deterministamente. Si se quita el paso 3, el grafo sigue siendo válido (solo menos pulido el núcleo).

## 5. Vistas para análisis

```sql
-- Grado signado por nodo (centralidad en red signada)
CREATE VIEW node_signed_degree AS
SELECT n.node_id, n.canonical, n.node_type,
       SUM(CASE WHEN e.polarity='positive' THEN 1 ELSE 0 END) AS pos_degree,
       SUM(CASE WHEN e.polarity='negative' THEN 1 ELSE 0 END) AS neg_degree,
       COUNT(*) AS degree
FROM nodes n JOIN edges e ON n.node_id IN (e.from_node_id, e.to_node_id)
GROUP BY 1,2,3;

-- Aristas agregadas por par+período (red por semestre)
CREATE VIEW edges_by_period AS
SELECT from_node_id, to_node_id, period,
       SUM(CASE WHEN polarity='positive' THEN 1 WHEN polarity='negative' THEN -1 ELSE 0 END) AS sign_sum,
       COUNT(*) AS n
FROM edges GROUP BY 1,2,3;
```

Algoritmos pesados (PageRank, Louvain, balance estructural) → export a `igraph`/`graph-tool` (DuckDB no los hace nativo).

## 6. Trade-offs y qué revisar al crecer

| Decisión | Trade-off | Cuándo revisar |
|---|---|---|
| DuckDB embebido | FK enforcement limitado (valida en insert, no cascada fuerte) → validar en el pipeline | si se necesita multi-escritor concurrente |
| Denormalizar fecha en edges | +velocidad temporal, −normalización (redundancia) | si la metadata de artículo cambia seguido |
| `node_id` secuencial | estable + legible, pero requiere un registro/contador | a 4.88M, considerar hash de canonical+type |
| Aliases en tabla con `UNIQUE(surface_norm)` | anti-duplicación fuerte, pero un surface ambiguo (homónimo) fuerza decisión | homónimos reales → desambiguación temporal |
| Todo en un `graph.duckdb` | simple, $0 | a 10⁷ aristas: particionar por year, o **DuckLake** para time-travel del grafo |
| Versionado por `genome_hash` | permite comparar corridas sin perder las viejas | si el archivo crece mucho → archivar versiones viejas |

**Lo que revisaría a escala 4.88M:** particionar `edges` por `year`, mover algoritmos a graph-tool, y evaluar DuckLake para versionar el grafo en el tiempo (2018→2026).
```
