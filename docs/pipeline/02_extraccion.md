# Pipeline de Extracción text2SG

> Sección de paper: **§ Metodología — Extracción de relaciones políticas**

---

## 1. Tarea de extracción

Dado un artículo de noticias y un conjunto de actores políticos pre-identificados, extraer todas las relaciones políticas signadas como tripletas:

```
(actor_origen, tipo_acto, actor_destino, polaridad, tema, cita_evidencia)
```

Donde:
- `actor_origen` / `actor_destino`: nombres de actores del texto
- `tipo_acto`: categoría del acto político (apoya, critica, acusa, etc.)
- `polaridad`: `+` (alianza/apoyo) / `−` (conflicto/ataque)
- `tema`: área temática (economía, seguridad, derechos humanos, etc.)
- `cita_evidencia`: fragmento textual que justifica la extracción

---

## 2. Arquitecturas del pipeline

### Modo `given_entities` — benchmark de optimización
Los actores políticos llegan **pre-computados** al extractor. Una sola llamada LLM extrae relaciones entre ellos.

```
[artículo + lista de actores] → LLM → relaciones
```

Ventaja: señal limpia para optimización (cambios de métrica atribuibles solo al prompt de relaciones). Usado en todo el loop evolutivo.

### Modo `end2end` — validación y producción
El modelo hace **dos llamadas**:
1. **NER pass:** detecta actores políticos desde el texto crudo
2. **REL pass:** extrae relaciones entre los actores encontrados (mismo formato que `given_entities`)

```
[artículo crudo] → NER-LLM → actores → REL-LLM → relaciones
```

Hallazgo: modelos fuertes (Sonnet, Gemini flash) rinden MEJOR en end2end que en given_entities — el NER propio captura actores más relevantes para el contexto que una lista pre-computada. El "NER tax" existe solo en modelos débiles (Qwen, Gemma4).

---

## 3. El genoma: tres artefactos co-evolucionados

El extractor se parametriza con un **genoma** de tres artefactos independientes:

### Artefacto A — `prompt_text`
El prompt del sistema dado al LLM. Define qué es una relación política válida, el formato de output JSON, y los ejemplos few-shot. Longitud: ~800–1200 tokens.

Decisiones relevantes en el campeón id15:
- Escrito en **inglés** (reduce sesgos de tokenización del español)
- **Abstención precision-first**: instrucción explícita de abstenerse si no hay evidencia textual clara
- **Few-shot:** 3 ejemplos (acto de apoyo, acto de crítica, caso ambiguo → abstenerse)

### Artefacto B — `ValidationConfig`
Post-proceso determinista ($0, sin LLM). Aplica reglas de corrección sobre el output raw:

| Regla | Propósito |
|---|---|
| `min_quote_len=15` | Descartar citas evidencia demasiado cortas (alucinación) |
| `require_actor_in_text=True` | Actor nombrado debe aparecer literalmente en el artículo |
| `deduplicate_relations=True` | Eliminar duplicados exactos |
| `normalize_polarity=True` | Canonicalizar `+1`/`-1` / `positivo`/`negativo` → `+`/`−` |

### Artefacto C — `AnalysisConfig`
Andamiaje pre-extracción ($0, sin LLM). Configura el contexto que acompaña al prompt:

| Flag | Propósito |
|---|---|
| `include_actor_types=True` | Añadir tipo de actor (político, gremial, mediático) |
| `include_date_context=True` | Fecha del artículo como contexto temporal |
| `chunk_long_articles=True` | Trocear artículos >6000 chars |
| `use_actor_aliases=False` | Desactivado en id15 (ruido > señal) |

---

## 4. Post-proceso de validación

`apply_validation(raw_output, validation_config)` corre localmente después de cada llamada LLM:

1. Parsear JSON del output (reintentos ante JSON inválido)
2. Filtrar relaciones que no pasan `min_quote_len`
3. Verificar que actor aparece en el artículo (previene alucinación de actores externos)
4. Deduplicar (misma tripleta extraída dos veces)
5. Normalizar tipos y polaridades a vocabulario canónico

---

## 5. Modelos evaluados

| Modelo | Arquitectura | f0.5 (v2, 207 art) | Costo relativo |
|---|---|---|---|
| **Gemini 2.5 flash-lite** (campeón id15) | given_entities | **0.928** | 1× (~$0.19/1k art) |
| Claude Sonnet 4.6 | end2end | **0.965*** | ~100× |
| Claude Haiku 4.5 | end2end | 0.901* | ~15× |
| Gemma4 (Ollama) | given_entities | ~0.85 | $0 (local) |
| Qwen2.5-7B (Ollama) | given_entities | ~0.80 | $0 (local) |

*Medido en muestra de 20 artículos (confirmación pendiente en 207).

**Decisión de producción:** gemini-2.5-flash-lite (batch API, 50% descuento → $0.05 in / $0.20 out por 1M tokens). Sonnet = techo de calidad / generador de gold; no extractor masivo.

---

## 6. Logging y observabilidad

Cada artículo extraído puede capturar:

```python
extract_article(article, collect_trace=True)
# → {
#     "relations": [...],        # relaciones finales (post-validación)
#     "raw_llm_output": "...",   # output crudo del LLM
#     "validation_drops": [...], # relaciones descartadas y razón
#     "n_actors_ner": 5,         # actores detectados en NER pass
#     "tokens_in": 1203,
#     "tokens_out": 287
# }
```

**Métricas proxy sin gold** (por shard):
- `rel_per_article`: media de relaciones/artículo (~2.5 en campeón)
- `pct_zero_relations`: % artículos sin ninguna relación extraída (proxy FN)
- `pct_validation_drops`: % relaciones descartadas por validación
- Distribución de `act_type` y `polarity`

Estas métricas son proxies de calidad (no validan correctitud) pero detectan degradación catastrófica (p. ej., `pct_zero_relations` > 40% indica problema).

---

*Implementación:* `text2sg/text2sg/extractor.py`, `text2sg/text2sg/validation.py`, `text2sg/text2sg/analysis.py`. Script de corrida: `text2sg/scripts/synth_run_model.py`.
