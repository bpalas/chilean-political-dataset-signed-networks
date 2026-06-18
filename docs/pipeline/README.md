# Pipeline docs — text2SG (Paper 2)

Documentación técnica del pipeline de extracción de relaciones políticas a escala.
Cada doc corresponde a una sección del paper 2.

| Doc | Sección del paper | Estado |
|---|---|---|
| [`00_alineacion_tesis.md`](00_alineacion_tesis.md) | Contexto: tesis vs paper 2 vs paper 3 | ✅ |
| [`01_corpus_prefiltro.md`](01_corpus_prefiltro.md) | § Datos — Corpus, gazetteer, léxico | ✅ |
| [`02_extraccion.md`](02_extraccion.md) | § Metodología — Pipeline text2SG, genoma | ✅ |
| [`03_evaluacion_optimizacion.md`](03_evaluacion_optimizacion.md) | § Evaluación — Gold sintético, Pareto, loop | ✅ |
| [`04_escala_storage.md`](04_escala_storage.md) | § Escala — Batch API, ER, DuckDB | ✅ |
| [`05_ner_alias.md`](05_ner_alias.md) | § NER — Detección de entidades, aliases, ER | ✅ |

**Números clave para el paper:**
- Corpus total: 4,884,321 artículos chilenos (2014–2026)
- Pre-filtro OR (gazetteer + léxico, 2019–2022): 383,675 artículos políticos
- Muestra de producción: 80,000 artículos (stratificada por año)
- Extractor campeón id15: f0.5 **0.928** / P 0.940 / R 0.884
- Costo extracción 80k (Batch API, gemini-2.5-flash-lite): ~$19–24
