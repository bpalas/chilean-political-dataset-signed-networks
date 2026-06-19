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
- ② ER 🔄 **muestra hecha** (`scripts/run_er.py` sobre 200 art → 415 nodos, guardas anti-sobre-fusión). **Falta escala**: 88.230 surface forms normalizados → necesita blocking (ver abajo).
- ③ RE 🔄 **muestra 200** (581 relaciones, `data/processed/re/relations.parquet`). Test gold en curso (`scripts/score_gold.py`). **Prod = Batch API** (subagentes no escalan: 80k ≈ 29 días).
- ④ Graph 🔄 embrionario: `data/processed/er/{nodes,edges}.parquet` (de la muestra).

## NER decisión (F3, 2026-06-18)
GLiNER local (`urchade/gliner_multi-v2.1`, threshold 0.4) para el volumen ($0, determinista). Haiku NO para el full (solo zona gris). spaCy descartado (no distingue party/coalition/movement). Eval: `scripts/eval_ner_gliner_vs_haiku.py`.

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
