# ROADMAP — text2SG a ≥80.000 noticias reales (escalable a 2M)

> Generado 2026-06-17 vía workflow multi-agente (4 investigaciones + verificación adversarial
> de los datos de Batch API por 2 verificadores independientes contra docs oficiales de Google).
> **Regla: dato verificado > dato reportado.**

## Hechos verificados del entorno (no re-descubrir)

- **Corpus real:** `clivaje-evolve/edgelist_grande_full 1/edgelist_grande_full.csv` — 1987 MB, 16 columnas.
  **CIFRAS CORREGIDAS (2026-06-17):** las "11.2M filas" eran un espejismo de `wc -l` (contó newlines DENTRO
  de los bodies). Reales: **350,153 filas-relación → 66,962 artículos ÚNICOS** (dedup por CONTENIDO; `news_index`
  se reusa, NO es clave). ⚠️ **El target de 80k EXCEDE el corpus (~67k disponibles).** Columnas: `news_index`,
  `publish_date`, `title`, `body`, `tema_local`, `from_node_label`/`to_node_label` (semilla del gazetteer),
  `sentiment`, `confianza`. Fechas 2014–2026 (pico 2021=10k).
- **Lago construido:** `text2sg/results/corpus/raw/articles/year=YYYY/*.parquet` (66,962 art) vía
  `text2sg/text2sg/corpus_data.py`. DuckDB lee el CSV de 2GB en ~5s. Ya no hay tier "2M" — el corpus entero es 67k.
- **Body real medido (3000 art):** mediana **829 tok**, media 1243 tok, p90 2795 tok. Cola larga.
- ~~Mojibake en `tema_local`~~ **DESCARTADO (2026-06-17):** el CSV es **UTF-8 válido y limpio** (verificado por ords: byte `\xc3\xa1`→225=á, sin U+FFFD; DuckDB lo lee bien). El `�` era artefacto de render de la consola Windows. **NO aplicar ftfy** (dañaría texto correcto). Solo leer/escribir en UTF-8.
- **Campeón id15** = `given_entities`, `few_shots: []`, prompt ~1166 tok. (No end2end, sin few-shots → baja el costo.)
- Extractor: `extractor.py` llama genai síncrono en líneas 143 (NER), 204 (verify), 236 (relaciones);
  `apply_validation` corre local línea 253 ($0).

---

## 1. Ingesta / pre-filtro (año + tópicos)

**No cargar el CSV de 2GB en pandas** (RAM). Usar DuckDB (streaming). Script nuevo `text2sg/corpus_data.py`:

1. **Dedup en una pasada DuckDB** (`QUALIFY row_number() OVER (PARTITION BY news_index) = 1`) →
   ~2.1M únicos, escribiendo Parquet particionado por `year`.
2. **Reparar encoding ANTES de filtrar** (`ftfy.fix_text` sobre `tema_local`/`title`/`body`). Load-bearing.
3. **Validar fechas** (descartar no-parseables a `year=__bad__` para auditar).
4. **Pre-filtro** = whitelist de ~30–50 `tema_local` políticos densos + rango de años (sobre Parquet, no CSV).
5. **Muestreo de 80k estratificado** por `year × tema_local`, `ORDER BY hash(news_index)` (reproducible).

Salida: `raw/articles/year=YYYY/*.parquet` con `article_id = news_index`.

---

## 2. Batch — ¿existe algo tipo OpenAI Batch para Gemini? **SÍ** (verificado)

Gemini Batch API en el **mismo SDK `google-genai`** que ya usás. Confirmado contra `ai.google.dev`.

| Ítem | Valor VERIFICADO |
|---|---|
| Descuento batch | **50% exacto** sobre input Y output |
| `gemini-2.5-flash-lite` batch | **$0.05 in / $0.20 out** por 1M (sync: $0.10 / $0.40) |
| Ventana | target 24h, **expiry duro 48h** (`JOB_STATE_EXPIRED`) |
| Input | JSONL ≤2GB / inline <20MB; cada línea con `key` + `request` |
| SDK | `files.upload` → `batches.create` → `batches.get` (poll) → `files.download`; reensamblar por `key` |
| Cuello real | enqueued tokens: **Tier1 10M / Tier2 500M / Tier3 1B**; 100 jobs concurrentes |

**Correcciones de la verificación (datos que NO se sostienen):**
- ❌ "Vertex 75 jobs/región" — refutado (Gemini batch usa pool dinámico, sin ese cap).
- ❌ RPM/RPD sync por tier — fuente tercera, no oficial (la página oficial remite a AI Studio).
- ❌ Límites OpenAI "200k req / 50M in-flight" — stale; doc actual = 50k req/batch, 200MB, 2000 batches/h.
- ⚠️ Audio $0.15 es tarifa **batch** (sync $0.30).

### Recomendación: **BATCH, no async**
Async síncrono choca con **RPD** mucho antes que con RPM (80k end2end = 160k llamadas/día). Batch no tiene RPD,
solo el cap de enqueued-tokens. Async solo para smokes de cientos de artículos.

### Costo y tiempo (rango honesto — medir antes de comprometer 2M)

| Escenario | n | BATCH | SYNC | Jobs Tier1/Tier2 |
|---|---|---|---|---|
| **END2END** (2 llamadas) | 80k | **~$24–55** | ~$49–110 | 30 / **1** |
| END2END | 2M | **~$608–1380** | ~$1216–2760 | 736 / 15 |
| GIVEN_ENT (1 llamada) | 80k | ~$16–34 | ~$32–68 | 18 / 1 |
| GIVEN_ENT | 2M | ~$403–806 | ~$806–1612 | 446 / 9 |

> **Rango $24 vs $55:** el extremo bajo usa los tokens REALES medidos (id15 sin few-shots, body mediano
> 829 tok → ~3680 in/600 out por artículo); el alto usa el supuesto conservador (4.3k in/llamada). La cola
> larga (p90 2795) puede moverlo. **F3 (smoke) clava el número real antes de escalar.** Para 80k el costo es
> chico igual; para 2M la diferencia importa.

**Tiempo:** batch = 1 ventana (≤24-48h) **por lote**, independiente del n. 80k en **Tier2 = 1 job, <24h**.
Subir a Tier2 (billing + $250 acumulados + 30 días) es la palanca que convierte 80k en un solo job.

---

## 3. Escala del pipeline — cambios concretos

**Reutilizar intacto** (stateless): `build_prompt`, `parse_llm_output`, `apply_validation`. **No tocar** `synth_data.py`.

1. **NUEVO `text2sg/corpus_data.py`** → `load_corpus_articles(...)` con el mismo shape que `load_synth_articles`.
2. **NUEVO `text2sg/batch_gemini.py`** → `run_extraction_batch(...)`: serializa JSONL con `key=news_index`
   (en end2end 2 líneas/artículo → **dos lotes encadenados**: NER → reensamblar unions → REL). Reintenta solo
   las `key` FAILED/EXPIRED. Trocea a <10M tok si Tier1.
3. **NUEVO `text2sg/scripts/corpus_run_model.py`**: `--corpus-parquet --year-range --tema-whitelist --batch --resume-from --limit`.
4. **Checkpointing:** shards `raw/extractions/year=YYYY/part-NNNN.parquet` + `state.json`/SQLite con `{article_id: status}`.
   (Hoy `synth_run_model.py` escribe todo al final → si crashea a 40k, se pierde todo.)
5. **Observabilidad sin gold:** por shard — tokens/costo, **relaciones/artículo**, **% con 0 relaciones** (proxy FN),
   distribución `act_type`, cobertura NER → `metrics.json`. Son proxies, no validan correctitud (ver §5).

---

## 4. Storage — **DuckDB + Parquet** (no graph DB dedicada)

KuzuDB (candidato embebido obvio) fue **archivado oct-2025**; Neo4j/ArangoDB = sobre-ingeniería para 10M aristas.
DuckDB hace analítica + grafo (recursive CTE / DuckPGQ) + ER (Splink) con un binario pip-installable.

**Capa 1 — RAW (Parquet por `year`):** escritura incremental idempotente. DuckDB = **un solo escritor**: cada worker
escribe su shard, la consolidación a `graph.duckdb` es single-writer.

**Capa 2 — GRAPH (`graph.duckdb`):** reusa el shape del gold v2 (`u_from`, `u_to`, `act_type`, `polarity`, `issue`, `evidence_quote`).

```sql
nodes(node_id PK, canonical_name, node_type, first_seen, last_seen, n_mentions, n_articles)
edges(edge_id PK, from_node_id, to_node_id, article_id, publish_date, act_type,
      polarity, issue, topic, evidence_quote, confianza, medio)   -- particionar por year,month
mentions(mention_id PK, surface_form, article_id, node_id, match_score, resolved_by)  -- salida de Splink
```

Grafo: recursive CTE nativo (vecinos/caminos); export a `igraph`/`graph-tool` para PageRank/Louvain (no `networkx` a 10M).
Upgrade futuro: **DuckLake** para time-travel del grafo (2018→2026).

---

## 5. Entity Resolution + Gold

### Canonicalización de actores (post-proceso, NUEVO `text2sg/er_resolve.py`)
Cascada precision-first:
1. **Gazetteer GRATIS** desde la extracción vieja: contar `from_node_label`+`to_node_label` de las 11.2M filas → curar top 500–1000.
2. **Reparar mojibake** (el fuzzy se rompe con `Bor�c`).
3. **Lookup exacto** contra gazetteer (80–90% del volumen, $0).
4. **Splink** (backend DuckDB) para la zona difusa: blocking por apellido × `type` (cross-type evita fusionar homónimos).
5. **flash-lite SOLO en zona gris** (batch, no online).
6. **Cargos por fecha** (`el presidente` 2018 ≠ 2024) usando `publish_date`.

**Riesgo dominante:** la ER es el cuello de **calidad**, no el storage. Un error se propaga a todo el grafo → precision-first.

### Gold = copia de noticias del corpus (ventaja medible)
1. Las noticias gold son artículos reales del **mismo corpus** → para el subconjunto compartido podés medir **P/R/f05 reales
   sobre datos reales** (matcheo por par `u_from,u_to`, como el scorer del sintético).
2. **Doble benchmark:** evolucionar contra **sintético v2** (señal limpia); **validar end2end** contra el gold-real-compartido
   (mide el NER tax sobre datos reales) antes de producción.
3. **Set humano N=200–500** estratificado por `year × tema_local`: exportar `(artículo, EXTRAJO, evidence_quote)` a planilla
   revisable; auditar P y % FN. Ancla las métricas-proxy a verdad humana. **Obligatorio antes de 2M.**

---

## Fases, camino crítico, riesgos

| Fase | Entregable | Esfuerzo | Depende |
|---|---|---|---|
| **F1 Ingesta** | `corpus_data.py`: CSV→Parquet, dedup, fix mojibake, prefiltro, muestra 80k | M | — |
| **F2 Batch runner** | `batch_gemini.py` + `corpus_run_model.py` | M-L | F1 |
| **F3 Smoke+calibración** | 200–500 art batch, medir tokens reales, clavar costo | S | F2 |
| **F4 Storage** | `graph.duckdb` + consolidación shards | M | F1 |
| **F5 Escala 80k** | batch Tier2 1 job + checkpointing + métricas | M | F2,F3,F4 |
| **F6 Entity Resolution** | `er_resolve.py`: gazetteer + Splink + zona gris | L | F4,F5 |
| **F7 Validación gold** | audit humano N=200–500 + P/R contra gold compartido | M | F5 |
| **F8 Escala 2M** | Tier2/3, troceo, DuckLake | L | F5,F6,F7 |

**Camino crítico:** F1 → F2 → **F3 (gate: no escalar sin medir tokens reales)** → F5 → F7 → [F4/F6 paralelo] → F8.

**3 riesgos:**
1. ~~Mojibake~~ **RESUELTO:** el CSV es UTF-8 limpio (verificado). No requiere reparación; solo leer/escribir UTF-8.
2. **Costo 2M se dispara** si tokens reales > medidos (p90 body 2795) → truncar body a 6000 chars (ya lo hace el código),
   medir en F3, considerar `given_entities` (NER pre-computado) → de ~$608 a ~$403 a 2M.
3. **ER sobre/sub-fusiona** y contamina el grafo → cross-type blocking + precision-first + auditar sobre corpus real (F7).

**Quick win esta semana:** escribir `corpus_data.py` y correr la pasada DuckDB de ingesta+dedup+fix-encoding sobre el
CSV de 2GB ($0, sin LLM). Sale el lago `raw/articles/` con ~2.1M únicos limpios + la query de muestreo de 80k. Bloqueante
de todo lo demás, no depende de Tier2/billing. Luego: smoke batch de 500 art (F3) para clavar el costo real.
