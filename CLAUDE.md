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

## Estado actual (2026-06-18)
- F1 Ingesta ✅ — muestra 80k en `data/processed/samples/political_2019_2022_80k.parquet`
- ① NER 🔄 **F3 cerrado: GLiNER gana** (head-to-head vs Haiku: igual cobertura, 0 ruido geográfico, mejor en person/party/coalition). Escalando a 80k vía `scripts/run_ner_gliner_80k.py` (checkpointed → `data/processed/ner/gliner/`). Config: `urchade/gliner_multi-v2.1`, threshold 0.4.
- ② ER ❌ código listo, gazetteer semilla 300, sin correr
- ③ RE (id15) ❌ genoma migrado, falta batch runner (`batch_gemini.py`, no está)
- ④ Graph ❌ `graph.duckdb` no existe

## NER decisión (F3, 2026-06-18)
GLiNER local para los 80k ($0, determinista). Haiku NO para el full (solo zona gris). spaCy descartado (no distingue party/coalition/movement). Evaluación: `scripts/eval_ner_gliner_vs_haiku.py`.

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
