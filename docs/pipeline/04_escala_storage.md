# Escala y Storage

> Sección de paper: **§ Metodología — Extracción a escala y almacenamiento del grafo**

---

## 1. Estrategia de extracción a escala

El extractor sincrónico choca con el límite de peticiones por día (RPD) de los modelos de API mucho antes que con el límite por minuto (RPM). Para 80k artículos en modo end2end = 160k llamadas/día → **batch API obligatorio**.

### Gemini Batch API

| Parámetro | Valor verificado |
|---|---|
| Descuento | 50% exacto sobre input Y output |
| `gemini-2.5-flash-lite` | $0.05 in / $0.20 out por 1M tokens (sync: $0.10 / $0.40) |
| Ventana | objetivo 24h, expiración dura 48h |
| Input | JSONL ≤2GB, cada línea con `key` + `request` |
| Cuello real | enqueued tokens: Tier1 10M / Tier2 500M |
| 80k en Tier2 | **1 job, <24h** |

**End2end = dos lotes encadenados:**
1. **Lote NER:** un request por artículo → output = lista de actores
2. **Reensamblar unions:** combinar actores detectados con el texto
3. **Lote REL:** un request por artículo con actores → output = relaciones

El `key` de cada request usa `article_id` (md5 del body) como identificador estable → reensamblar los resultados del lote por clave, re-enviar solo los `FAILED`/`EXPIRED`.

### Costo estimado

| Escenario | n artículos | Costo batch | Costo sync |
|---|---|---|---|
| Smoke (calibración) | 500 | ~$0.15 | ~$0.30 |
| **Producción 80k** | 80,000 | **~$19–24** | ~$38–48 |
| Escala total (2019–2022 OR) | 383,675 | ~$95–115 | ~$190–230 |
| Universo 4.88M | 4,880,000 | ~$1,200–1,500 | — |

> El rango depende de la distribución real de longitud de body (mediana 551 tok, p90 ~1,800). **F3 smoke de 500 artículos clava el número real antes de comprometer 80k.**

---

## 2. Checkpointing (F2/F5)

El runner sincrónico (`synth_run_model.py`) escribe todos los resultados al final → si crashea en el artículo 40,000 se pierde todo. El runner de escala necesita checkpointing incremental:

```
raw/extractions/year=YYYY/part-NNNN.parquet   ← shards de resultados
raw/extractions/state.json                     ← {article_id: "done"|"failed"}
```

Al reiniciar, el runner lee `state.json` y omite los `article_id` ya procesados. Los `failed` se re-intentan con lote separado.

---

## 3. Entity Resolution (ER)

Los actores extraídos en modo end2end tienen variaciones superficiales (`"Gabriel Boric"`, `"el presidente Boric"`, `"Boric Font"`). La canonicalización es **precision-first** para no fusionar homónimos:

```
1. Gazetteer exacto ($0)       → "gabriel boric" → node_id=42    [~80% del volumen]
2. Splink (DuckDB backend)     → blocking por apellido × act_type → fuzzy match
3. LLM zona gris (flash-lite)  → solo los casos que Splink no resuelve con confianza
4. Cargos por fecha            → "el presidente" en 2018 ≠ en 2024 (usar publish_date)
```

**Riesgo principal:** la ER es el cuello de **calidad**, no el storage. Un error de fusión se propaga a toda la red temporal. Cross-type blocking (no fusionar actores de tipos distintos) previene la mayoría de los homónimos.

---

## 4. Storage: DuckDB + Parquet

No se usa graph DB dedicada. KuzuDB fue archivado oct-2025; Neo4j/ArangoDB = sobre-ingeniería para 10M aristas.

**Capa 1 — RAW (Parquet particionado por year):**
```
raw/articles/year=YYYY/*.parquet        ← corpus canónico (dedup por body)
raw/extractions/year=YYYY/*.parquet     ← relaciones extraídas + tokens + trace 1%
```

**Capa 2 — GRAPH (`graph.duckdb`):**
```sql
nodes(node_id, canonical_name, node_type, first_seen, last_seen, n_mentions, n_articles)
edges(edge_id, from_node_id, to_node_id, article_id, publish_date,
      act_type, polarity, issue, topic, evidence_quote, confianza, medio)
mentions(mention_id, surface_form, article_id, node_id, match_score, resolved_by)
```

**Consultas analíticas:** DuckDB recursive CTE para vecinos/caminos; export a `igraph` / `graph-tool` para PageRank/Louvain (no `networkx` para grafos de 10M aristas).

---

## 5. Validación antes de publicar (gate F7)

Antes de publicar cualquier análisis sobre el grafo extraído:

1. **Audit humano N=200–500:** exportar `(artículo, EXTRAJO, evidence_quote)` a planilla revisable. Medir P y % FN manualmente. Ancla las métricas-proxy a verdad humana.
2. **P/R contra gold compartido:** el corpus clivaje tiene artículos reales del mismo universo. Para el subconjunto compartido, medir P/R/f0.5 reales (matcheo por par `u_from, u_to`). Completa la cadena: sintético → real → prod.
3. **Umbral mínimo:** P ≥ 0.85 / f0.5 ≥ 0.88 sobre gold real antes de escalar a 383k / 4.88M.

---

## 6. Roadmap de fases

| Fase | Entregable | Estado |
|---|---|---|
| **F1 Ingesta** | `corpus_data.py`: parquet, gazetteer, léxico, muestra 80k | ✅ Completo |
| **F2 Batch runner** | `batch_gemini.py` + `corpus_run_model.py` | Pendiente |
| **F3 Smoke** | 500 art batch → tokens reales, costo, calidad NER | Pendiente ($0.15) |
| **F4 Storage** | `graph.duckdb` + consolidación shards | Pendiente |
| **F5 Escala 80k** | batch Tier2, checkpointing, métricas proxy | Pendiente (~$20) |
| **F6 Entity Resolution** | `er_resolve.py`: gazetteer + Splink + zona gris | Pendiente |
| **F7 Validación gold** | audit humano N=200–500 + P/R real | Pendiente |
| **F8 Escala 383k** | OR amplio (gaz+léxico), re-run F5 config | Pendiente (~$100) |

**Camino crítico:** F1 ✅ → F2 → **F3 (gate)** → F5 → F7 → [F4/F6 paralelo] → F8

---

*Implementación:* `text2sg/text2sg/corpus_data.py` (ingesta), `text2sg/scripts/synth_run_model.py` (extracción). Pendiente: `text2sg/batch_gemini.py`, `text2sg/scripts/corpus_run_model.py`, `text2sg/er_resolve.py`.
