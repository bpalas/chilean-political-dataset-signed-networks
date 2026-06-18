# ROADMAP DE PRODUCCIÓN — text2SG sobre noticias reales

> Complementa `roadmap-escala-80k.md` (ingesta, batch, storage, ER, gold). Este doc agrega las
> dos capas que faltaban para PRODUCCIÓN: **observabilidad/logs** y **arquitectura de modelo/tokens**,
> más las preocupaciones de ops (re-runs, actualización incremental, quality gates).

## Estado actual de logging (hecho, verificado en código)

| Pieza | Guarda durable | NO guarda |
|---|---|---|
| `extractor.py` → `preds.json` | `{article_id, entities, relations, tokens}` | output crudo del LLM (se descarta líneas 151/212/240), desglose NER-vs-REL, qué tiró validación B, prompt enviado |
| Pareto `pareto/<arch>.json` | genoma, P/R, `parent_id`, `gradient_tags`, `subset_metrics` | **rationale/change/lente** de cada mutación (el "por qué") |
| `pick` | `*_expand_diag/examples/tools.json` | — |
| Workflow loop | retorna `trajectory` en memoria | no lo escribe a archivo del repo |

**Conclusión:** sabemos el QUÉ (scores), no el PORQUÉ (razonamiento). Capturar el crudo cuesta ~0 tokens.

---

## A. Capa de observabilidad (responde "ver si sale bien y cómo piensa cada iteración")

### A.1 Traza por artículo (extracción a escala)
Cambio en `extractor.py`: `extract_article`/`extract_entities` devuelven opcionalmente la traza (param `trace=True`, default off → no rompe tests). Escribir JSONL por shard:

```jsonc
{ "article_id", "ts", "model", "genome_hash", "architecture",
  "ner":  { "raw_output", "parsed_actors", "tok_in", "tok_out" },
  "rel":  { "prompt_hash", "raw_output", "parsed_relations", "tok_in", "tok_out" },
  "validation": { "dropped": [{rel, reason}], "kept_n" },   // por qué B descartó cada una
  "final": { "n_relations", "abstained": bool } }
```
El `raw_output` captura el razonamiento (sobre todo en modo `debate`). Permite auditar "¿por qué perdió/inventó X?".

### A.2 Estrategia de retención (decisión de storage, no de tokens)
- **100% siempre:** métricas compactas por artículo (rel/artículo, % con 0 rels = proxy FN, distribución `act_type`, tokens/costo) → `metrics.parquet`.
- **Traza completa:** 100% en smoke/validación; **muestreada (1–5%) en producción** (el crudo de 2M ocupa). Sampling estratificado por `year × tema` + 100% de los que abstienen (los 0-rels son los sospechosos).

### A.3 Log de iteración evolutiva (el "cómo piensa cada lente")
Dos cambios chicos, backward-compatible:
1. **`ParetoEntry` gana campos opcionales** `rationale`, `lens`, `change`, `iter`. `register_run` los acepta; el workflow los pasa. → `board` puede mostrar POR QUÉ existe cada genoma, no solo su score.
2. **Persistir el `trajectory`** del workflow a `results/synthetic/runs/loops/<arch>_<ts>.json` (hoy solo se retorna en memoria).

---

## B. Arquitectura de modelo / tokens (responde "buen LLM para ahorrar tokens")

**Principio:** el desperdicio es arquitectónico (body enviado 2×, NER repetido), no del modelo. Modelo bueno = 10-20× por token → usarlo en todo sale más caro.

### B.1 Estructura recomendada: NER-una-vez + `given_entities` + híbrido quirúrgico
1. **NER una sola vez por artículo**, persistido en `nodes`/`mentions`. Modelo: **bueno** (calidad crítica, amortizada — todo depende de los actores). Una vez por los ~2.1M → barato amortizado.
2. **Extracción de relaciones = `given_entities`** (1 llamada, body 1×) con **flash-lite barato**. Es lo que se repite (en producción y en cada re-extracción de la evolución).
3. **Zona gris de ER** con modelo bueno, batch, solo casos dudosos (~zona).

Efecto: el modelo caro toca ~10% del volumen (una vez); el barato hace el 90% repetido.

### B.2 Ahorro de tokens — palancas (en orden de impacto)
| Palanca | Ahorro | Costo |
|---|---|---|
| NER una vez + `given_entities` (no end2end cada run) | body 1× en vez de 2× → ~-35% input; gratis en re-runs | persistir actores |
| Truncar body a 6000 chars | ya implementado (`body[:6000]`) | — |
| Pre-condensar artículo (modelo bueno extrae el span político) | paga solo si **re-extraés** muchas veces el mismo set (evolución), no en pasada única de prod | +1 llamada |
| Prompt más terso con modelo capaz | -fixed overhead/llamada (~1166 tok × N) | calidad |

> Regla: condensación/pre-proceso paga en el set de **evolución** (re-uso N veces), NO en la pasada única de 2M.

---

## C. Ops de producción (más allá del 80k)

- **Idempotencia + re-runs:** clave `(article_id, genome_hash)`. Re-correr con genoma nuevo no pisa lo viejo → comparar versiones del grafo.
- **Versionado de datos:** cada corrida etiqueta `genome_hash` + `model` + `prompt_hash` en cada arista → trazabilidad de qué versión produjo qué.
- **Actualización incremental (news diario):** el corpus crece; pipeline incremental que procesa solo `article_id` nuevos (el `state.json`/SQLite ya lo permite).
- **Quality gates antes de escalar:** F3 (smoke, costo real) y F7 (audit humano N=200–500) son gates duros. No escalar a 2M sin pasar ambos.
- **Control de costo:** presupuesto por corrida (abortar si tokens proyectados > X); el batch ya da costo predecible por lote.
- **Monitoreo de deriva:** comparar distribuciones (rel/artículo, % abstención, act_types) entre corridas → detectar si un genoma nuevo degeneró sin necesidad de gold.

---

## Decisiones LOCKED (2026-06-17)

1. **Arquitectura:** **NER (modelo bueno) → unimos (entity resolution) → `given_entities` (flash-lite) → grafo.**
   El NER+ER produce la lista de actores canónicos por artículo; las relaciones se extraen con flash-lite
   sobre esos actores. NER y ER una vez por artículo (amortizado); relaciones repetibles barato.
2. **Logging:** métricas 100% (`metrics.parquet`) + crudo muestreado 1–5% (`trace.jsonl`) + 100% de los que abstienen.
3. **Modelo NER:** evaluar en F3 (smoke) entre **GLiNER** (zero-shot, local, $0), **spaCy es_core_news_lg**, y
   **NER vía Gemini bueno**. Decidir con datos, no a ciegas. El usuario prefiere un modelo NER dedicado si rinde.

## Orden sugerido (sin gastar LLM todavía)

1. ✅ **F1 Ingesta — HECHO (2026-06-17, $0).** Corpus real = `Downloads/data/raw/articles_all.parquet`
   (**4.88M art chilenos únicos**, 2014-2026). Lago canónico en `text2sg/results/corpus/news/articles/`.
   Gazetteer de 300 actores políticos (de clivaje) en `results/corpus/gazetteer.json`. Filtro político
   (≥2 actores) → **497k candidatos políticos**. **Muestra lista:** `results/corpus/samples/political_2019_2022_80k.parquet`
   (80k art, 2019:14.8k/2020:18.3k/2021:24.8k/2022:22.1k, 3.46 actores/art, body mediana 551 tok).
   Código en `corpus_data.py` (build_news_corpus_parquet / build_gazetteer / load_political_articles), 8 tests.
2. **Instrumentar logging** (`trace=True` en extractor + campos rationale en ParetoEntry + persistir trajectory) — $0, código.
3. **F3 smoke** (primer gasto chico, ~$1-3) — clava costo real + calidad del NER → resuelve decisiones 2 y 3.
   Costo estimado del run 80k 2019-2022 (NER-once + given_entities, batch): **~$19**.
