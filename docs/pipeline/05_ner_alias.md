# NER y Diccionario de Aliases

> Sección de paper: **§ Metodología — Detección de entidades y resolución de alias**

---

## 1. Decisión: NER-first para producción

El pipeline de producción separa explícitamente NER y RE en dos pasos:

```
Artículo crudo
    │
    ▼
① NER pass  ─── detecta TODAS las entidades + sus alias en el artículo
    │             output: {canonical, type, role, surface_forms[]}
    ▼
② ER / Dedup ── une aliases entre artículos → IDs canónicos estables
    │             gazetteer → rapidfuzz → Splink → LLM zona gris
    ▼
③ RE pass ────── extrae relaciones entre IDs canónicos (modo given_entities)
    │             actors = {id: canonical_name, ...}
    ▼
④ Graph ──────── DuckDB: nodes + edges + mentions
```

**Fundamento:** la separación NER/RE permite optimizar cada paso independientemente.
El paso ER entre NER y RE es el que da **consistencia al grafo**: sin él, "Boric" en
un artículo y "el mandatario" en otro no se unen como el mismo nodo.

---

## 2. Scope del NER: todas las entidades

A diferencia del modo `given_entities` (que solo usa actores del gold), el NER de
producción captura **todas las entidades mencionadas**, sin filtro político estricto:

| Tipo | Ejemplos |
|---|---|
| `person` | "Gabriel Boric", "Elisa Loncon", "Fabiola Campillai" |
| `party` | "PS", "UDI", "Revolución Democrática", "La Lista del Pueblo" |
| `institution` | "Ministerio de Hacienda", "Corte Suprema", "Contraloría" |
| `coalition` | "Apruebo Dignidad", "Chile Vamos", "el Frente Amplio" |
| `movement` | "el estallido social", "la convención", "el movimiento feminista" |
| `org` | "CUT", "SQM", "Codelco", "La Tercera" |
| `location` | solo cuando es actor político ("La Moneda", "el Congreso") |

**Rasgo importante:** un mismo artículo usa múltiples formas para la misma entidad.
El NER captura TODAS las formas superficiales (`surface_forms`) como primer paso hacia
el diccionario de aliases.

---

## 3. Diccionario de aliases por nodo

Estructura por entidad:

```python
{
  "entity_id": "POL-0042",          # ID estable (hash o secuencial)
  "canonical_name": "Gabriel Boric Font",
  "type": "person",
  "role": "Presidente de Chile",    # rol en el período de los artículos
  "aliases": [                      # TODAS las formas superficiales vistas
    "Gabriel Boric",
    "Boric",
    "el presidente",
    "el mandatario",
    "el jefe de Estado",
    "Boric Font",
    "el Presidente Boric"
  ],
  "first_seen": "2021-03-15",       # en el corpus
  "n_articles": 4821,
  "source": ["clivaje", "ner_extracted", "manual"]
}
```

**Construcción incremental:**
1. **Seed gratis:** `gazetteer.json` (300 actores top de clivaje, from_node_label/to_node_label)
2. **NER batch 5k art:** recolectar surface_forms por canonical → cluster con rapidfuzz ≥85%
3. **Revisión manual top-100:** cubre ~80% del volumen con 1-2h de trabajo
4. **Iterativo:** cada batch nuevo agrega aliases; los `match_score < 0.85` van a Splink

---

## 4. Modelos por entorno

| Entorno | NER | RE | Costo |
|---|---|---|---|
| Dev / in-sesión (Max plan) | Haiku workflow 1-agente/art | Haiku given_entities | $0 |
| Producción | Gemini flash-lite batch | Gemini flash-lite batch | ~$4 NER + ~$20 RE / 80k |
| Validación / techo | Sonnet workflow | Gemini flash-lite | ~~$150 NER / 80k~~ solo muestra |

**Haiku como NER de desarrollo:** demostrado eficaz — NER tax ≈ 0.03 f05 vs given_entities
con prompt id15 base; con prompt optimizado (Haiku-evolve r3 GE: f05=0.9282) la brecha
se cierra. Ideal para iterar en sesión sin API key.

---

## 5. NER prompt — principios de diseño

El prompt de NER es distinto al de RE:

- **Más corto** (output esperado ~100-300 tokens vs ~500 en RE)
- **Sin few-shot exhaustivos** (las entidades son más simples de identificar que los actos)
- **Instrucción de coreferences explícita:** "para cada entidad, lista TODAS las formas
  en que el artículo se refiere a ella"
- **Sin filtro político estricto:** capturar cualquier entidad nombrada relevante
- **Role heurístico:** inferir rol del contexto ("candidato a presidente en 2021",
  "ministro de salud", "dirigente sindical")

---

## 6. ER: Entity Resolution entre artículos

Después del NER, las menciones de distintos artículos se unifican:

```
"Boric" (art A) + "Gabriel Boric" (art B) + "el mandatario" (art C)
    → todos → entity_id=POL-0042 (canonical: "Gabriel Boric Font")
```

**Pipeline ER:**

```python
# 1. Gazetteer lookup exacto / normalized (lower + strip) — O(1)
entity_id = gazetteer.get(normalize(surface_form))

# 2. Fuzzy match si no hay exacto
candidates = rapidfuzz.process.extract(surface_form, gazetteer_keys, score_cutoff=85)
if len(candidates) == 1:
    entity_id = candidates[0]

# 3. Splink para casos ambiguos (varios candidatos o score 70-85)
# bloqueo por primer apellido o token principal
# features: jaro-winkler, type-match, role-context

# 4. LLM zona gris (Haiku, in-sesión o flash-lite batch)
# solo los casos que Splink reporta confidence < 0.80
# prompt: "¿'X' y 'Y' se refieren a la misma entidad en Chile 2020? sí/no/no-sé"

# 5. Cargos temporales: "el presidente" resuelve distinto en 2017 vs 2022
entity_id = resolve_by_role(surface_form, publish_date, role_timeline)
```

**Riesgo principal:** fusión incorrecta de homónimos (e.g., dos personas con apellido
"Morales"). Cross-type blocking (nunca fusionar `person` con `institution`) y umbral
conservador (solo fusionar con confianza ≥0.90) minimizan el riesgo.

---

## 7. Tabla: decisiones tomadas

| Decisión | Opción elegida | Descartada | Razón |
|---|---|---|---|
| Scope NER | Todas las entidades | Solo políticos | Cobertura > precisión inicial |
| Storage aliases | DuckDB `mentions` table | JSON file | Queryable, integrado al grafo |
| ER fuzzy | rapidfuzz + Splink | LLM-only | $0 primero, LLM solo zona gris |
| Graph DB | DuckDB + Parquet | Neo4j, KuzuDB | Sin servidor, SQL, $0 |
| NER dev | Haiku in-sesión | API key | Gratis en Max plan |
| NER prod | Gemini flash-lite batch | Haiku | 15x más barato, misma calidad |

---

*Implementación pendiente:* `text2sg/text2sg/ner.py` (NER prompt + schema),
`text2sg/er_resolve.py` (gazetteer + rapidfuzz + Splink), tabla `mentions` en `graph.duckdb`.
