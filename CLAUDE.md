# CLAUDE.md — chilean-political-dataset-signed-networks

Dataset de redes políticas signadas chilenas + pipeline de extracción **text2SG**
(paper 2). Extrae tripletas signadas `(actor → acto → actor, polaridad, tema)` de
noticias chilenas a escala.

## Comandos
- `python -m pytest tests/ -q` — suite (15 tests, sin red ni LLM)
- `python scripts/build_topic_model.py --lake … --gazetteer … --out …` — BERTopic

## Arquitectura del pipeline (flujo del grafo)
NER (GLiNER) → ER (unir aliases) → RE `given_entities` (id15, flash-lite) → `graph.duckdb`
- `text2sg/corpus_data.py` — ingesta DuckDB+Parquet, pre-filtro político (gazetteer+léxico), muestreo
- `text2sg/ner_gliner.py` — **Pasada 1 NER de producción**: GLiNER zero-shot local ($0), labels ES → tipos canónicos, chunking + char_span
- `text2sg/er.py` — entity resolution: gazetteer → rapidfuzz → Splink → LLM zona gris
- `text2sg/prompts/id15_champion.json` — extractor campeón (f0.5 0.928 / P 0.940 / R 0.884)
- `.claude/agents/ner-extractor.md` — agent Haiku para descubrimiento de gazetteer + zona gris (coalition/movement), NO para el 80k full
- `workflows/haiku_ner_discovery.workflow.js` — NER con Haiku (sesión, sin API key)

## Estado actual (2026-06-19)
- F1 Ingesta ✅ — muestra 80k en `data/processed/samples/political_2019_2022_80k.parquet`
- ① NER ✅ **COMPLETO (80.000 art, 909.811 menciones, 11.4/art, $0)** vía `scripts/run_ner_gliner.py`. Tipos: person 51% / institution 26% / party 13% / org 6% / coalition 3% / movement 1%. Salida: `data/processed/ner/gliner/`.
- ② ER ✅ **a escala** (`text2sg/er_resolve.py` con blocking por token + guardas): 96.990 surface forms → 79.643 nodos en ~34s. `scripts/run_er.py` (muestra) / `resolution_80k.json` (escala).
- ③ RE 🔄 **muestra 200** (581 rel) + **test gold**: detección f0.5 0.892 (undirected), labeling +act_type 0.743. **Prod = Batch API** (subagentes no escalan: 80k ≈ 29 días).
- ④ Graph ✅ **poblado**: `graph.duckdb` vía `scripts/build_graph.py` — 80k articles, 79.643 nodos, 88.230 aliases, 909.811 mentions, 562 edges. Red signada queryable (Piñera deg 77 +24/−39). Aristas solo de la muestra 200 (RE de prod pendiente).

## Post-proceso del grafo (flujo de curación, 2026-06-20)
Tras poblar `edges`, el grafo se cura EN CAPAS: determinista primero (barato, sin riesgo),
LLM (Sonnet) solo el grey-zone semántico. Reproducible para re-correr al escalar a 402k.

1. **Edges** — `scripts/load_gemini_edges.py`: RE (`re_gemini/relations_gemini.parquet`) →
   `edges`, linkeo por `surface_norm` del ER (96% resuelto; precision-first: ambas entidades
   deben resolver). Filtra `co_occurs` (sin polaridad) y polaridad nula. Las vistas
   `node_signed_degree` / `edges_by_period` se recalculan solas. [80k: 599k rel → 435k aristas.]
2. **Capa 1 — determinista** — `scripts/curate_propose.py` (PREVIEW, no toca DB): merges por
   (a) canónico exacto normalizado, (b) dict de siglas (`SIGLAS`: UDI↔Unión Demócrata Indep.,
   FA↔Frente Amplio…), (c) alias distintivo compartido (≥2 tokens, mismo tipo). Escribe
   `curation/deterministic_merges.json`; `--apply` lo copia a `curations.json`.
   [2026-06-20: 51 grupos, 101 nodos absorbidos — Boric ×4, Senado ×4, Hacienda ×8, 7 siglas.]
3. **Capa 2 — candidatos para Sonnet** (PENDIENTE): pares top-grado con `token_sort_ratio≥85`
   + mismo tipo (cross-type bloqueado) que NO resolvió la capa 1 → grey-zone para adjudicar.
4. **Capa 3 — Sonnet** — `workflows/sonnet_curate.workflow.js`: adjudica el grey-zone
   (Gobierno/Ejecutivo/Estado, "PC de China" mal etiquetado) → `curations.json`. Precision-first:
   ante la duda NO fusiona; nunca cruza tipos.
5. **Capa 4 — apply** — `scripts/curate_apply.py`: aplica merges/updates determinísticamente
   (maneja UNIQUE en aliases/edges, guarda anti-sobrefusión: bloquea 2 canonicals largos con
   `token_sort_ratio<60`). Recomputa `n_mentions` y `degree`.

Dato sucio histórico (lo resuelve el flujo): "Congreso" con canonical "Senado"; "Partido
Comunista de China" deg 5.990 = casi seguro el PC **de Chile** → capa 3.

## NER decisión (F3, 2026-06-18)
GLiNER local (`urchade/gliner_multi-v2.1`, threshold 0.4) para el volumen ($0, determinista). Haiku NO para el full (solo zona gris). spaCy descartado (no distingue party/coalition/movement). Eval: `scripts/eval_ner_gliner_vs_haiku.py`.

## NER rendimiento — medido en RTX 4070 8GB (2026-06-19)
Profiling (`scripts/profile_ner.py`) demostró que NER es **kernel-launch-bound**, NO CPU-tokenización ni GPU-compute: VRAM plana en 2.38GB, throughput plano a cualquier batch, 68% del tiempo en un sync CPU↔GPU dentro de GLiNER. **Un cambio de lenguaje (Go/Rust/C++) no toca el cuello** — el cómputo caliente ya es CUDA/Rust.
- **fp16 es la palanca real: ~1.7x** (8.8→13.2 art/s single-proc), paridad de entidades 0.99 vs fp32 (`scripts/profile_ner_opt.py`). Usar `--fp16` en prod; default sigue fp32 (los 80k ya extraídos en fp32, no mezclar). bf16 descartado (paridad 0.93).
- **MP ya NO ayuda** (`scripts/bench_ner_mp.py`): con el batching de `extract_batch` un proceso satura la GPU; 2 workers fp32 son MÁS lentos que 1, 3+ revientan los 8GB. Default `--workers` bajado 4→2. (El supuesto viejo "GPU 35x sobrada → paraleliza en CPU" quedó **falso** tras el fix de batching.)
- **ONNX descartado: 16x más LENTO** (`scripts/export_ner_onnx.py`). El loader ONNX de GLiNER no respeta `providers=[CUDA]` (corre en CPU) y el head de spans es un LSTM con shapes variables (peor caso ONNX-CUDA). Export correcto (Jaccard 0.99) pero inservible.

## ER a escala — dimensionamiento (2026-06-19)
88.230 surface forms normalizados; **63% aparecen 1 sola vez** (cola larga). El clustering in-memory (`er_resolve.py`) NO escala a 88k sin **blocking** (por apellido/token × tipo). Núcleo del grafo = actores frecuentes (≥3 menciones). Siglas (UDI, DC, RN, PS) requieren diccionario curado sigla↔nombre (no fuzzy). Guardas ya implementadas: cross-type, apellido para personas, umbral 90.

## Datos
- Gold de validación: `data/gold/synthetic_v2/` (287 art / 914 rel / split 207+75) — gitignored
- `data/` completo está gitignored; se baja con `python scripts/download.py`

## Gotchas
- Paquete = `text2sg/` (no `pipeline/`); imports `from text2sg.…`. `pythonpath=["."]` en pyproject resuelve pytest.
- `�` en consola Windows = artefacto de render (cp1252), NO mojibake. El corpus es UTF-8 limpio. **No usar ftfy.**
- El motor evolutivo (pareto/fitness/mutate/gold maker) vive en `text2graph-evolve`, NO acá. Este repo consume id15.
- id15 = `given_entities`, sin few-shots, prompt en inglés (precision-first, abstención).
- Estamos en 2026; ventana paper 2 = 2019–2022 (estallido → rechazo).

## Repos hermanos (en ../)
- `tesis-msc-datascience` — paper de análisis (extractor viejo, f0.5 ~0.86, corpus 64k)
- `clivaje-evolve` — análisis + track algorítmico (paper 3); `src/` congelado reproduce la tesis
- `text2graph-evolve` — origen de la migración; motor evolutivo + gold v2 + campeones

## Convenciones
- Docstrings/comentarios en español; código y prompts de producción según el módulo.
- Precision-first en todo el pipeline (un FP contamina el grafo; un FN solo omite).
- `article_id = md5(body)` (content-addressed, idempotente entre re-ingestas).
