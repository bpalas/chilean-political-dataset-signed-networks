# Corpus y Prefiltro Político

> Sección de paper: **§ Datos — Corpus y selección de artículos políticos**

---

## 1. Fuente de datos

El corpus de noticias chilenas proviene de dos fuentes del mismo universo:

| Fuente | Artículos únicos | Cobertura | Columnas clave |
|---|---|---|---|
| **Corpus grande** (`articles_all.parquet`, 6.8 GB) | **4,884,321** | 2014–2026 | `id`, `title`, `body`, `source`, `publish_date`, `year` |
| **Corpus clivaje** (`edgelist_grande_full.csv`, 2 GB) | 66,962 | 2014–2026 | igual + `tema_local`, `from_node_label`, `to_node_label` |

El corpus clivaje es el subconjunto etiquetado (relaciones extraídas manualmente, `tema_local`) que se usa como semilla del gazetteer y del gold sintético. El corpus grande es la fuente de producción.

**Medios:** biobiochile (478k), cooperativa (405k), latercera (297k), adnradio, elmostrador, lacuarta, t13, 24horas, df.cl, emol (top-10 representan ~60% del corpus).

**Body:** mediana 417 tokens / p90 1,002 tokens (corpus grande). Mediana 551 tokens en la submuestra política 2019–2022.

---

## 2. Gazetteer de actores políticos

El gazetteer se construye de forma $0$ desde las etiquetas de la extracción vieja del corpus clivaje (`from_node_label` + `to_node_label`, ~350k filas-relación). Ranking por frecuencia → top-300 actores políticos nombrados.

```
build_gazetteer(clivaje_csv, top_n=300) → 300 nombres (minúscula)
Persistido en: text2sg/results/corpus/gazetteer.json
```

Top-10 actores del gazetteer (refleja el período 2014–2026):
`gabriel boric`, `sebastián piñera`, `josé antonio kast`, `michelle bachelet`,
`carolina tohá`, `camila vallejo`, `evelyn matthei`, `mario desbordes`,
`mario marcel`, `jaime bellolio`

---

## 3. Léxico político

Para artículos que no nombran a ninguno de los top-300 actores por nombre pero sí discuten política institucionalmente (resoluciones del Senado, proyectos de ley, campañas electorales sin nombrar candidatos), se construye un léxico curado de 65 términos.

**Categorías:**

| Categoría | Ejemplos |
|---|---|
| Roles | ministro/a, diputado/a, senador/a, gobernador/a, alcalde/a, subsecretario/a |
| Instituciones | senado, cámara de diputados, congreso nacional, tribunal constitucional, contraloría, la moneda |
| Partidos y coaliciones | udi, renovación nacional, partido socialista, frente amplio, democracia cristiana, evópoli, apruebo dignidad |
| Procesos electorales | plebiscito, elecciones presidenciales, segunda vuelta, convención constitucional |
| Actos legislativos | acusación constitucional, interpelación, proyecto de ley, moción parlamentaria |
| Términos de clivaje | estallido social, 18 de octubre, apruebo, rechazo, reforma tributaria, reforma de pensiones |

```
build_political_lexicon(extra=None) → 65 términos (minúscula)
```

---

## 4. Pre-filtro político (OR amplio)

Un artículo se considera **político** si cumple al menos una condición:

```
(matched_actors ≥ 2)                    -- gazetteer: nombra ≥2 actores distintos
OR
(matched_lexicon ≥ 3)                   -- léxico: ≥3 términos institucionales distintos
```

El umbral `≥ 2 actores` apunta a artículos con potencial de RELACIÓN (dos actores en el mismo texto = señal de interacción). El léxico con `≥ 3` hits reduce el ruido de menciones incidentales.

### Resultados del filtro (ventana 2019–2022)

| Filtro | Artículos | % del corpus grande |
|---|---|---|
| Sin filtro (2019–2022 completo) | ~800,000 | 100% |
| Solo gazetteer (≥2 actores) | 161,830 | 20.2% |
| **OR amplio (gaz OR léxico≥3)** | **383,675** | **47.9%** |
| Delta: solo léxico | 221,845 | +137% sobre gazetteer |

**Distribución anual (OR amplio, 2019–2022):**

| Año | Artículos | Hito de cleavage |
|---|---|---|
| 2019 | 70,717 | Estallido social (oct) |
| 2020 | 90,444 | Pandemia + plebiscito apruebo |
| 2021 | 116,618 | Convención constitucional + elección Boric/Kast |
| 2022 | 105,896 | Gobierno Boric + plebiscito rechazo |
| **Total** | **383,675** | — |

### Ejemplos de artículos capturados solo por léxico

- "Ministra (s) de RREE encabeza lanzamiento de segunda ronda de reuniones APEC 2019"
- "CUT llama a oponerse a proyecto para adaptar jornadas laborales"
- "Gendarmería presentó querella por cohecho y asociación ilícita por celdas VIP"

Estos artículos mencionan roles institucionales ("Ministra", "proyecto") sin nombrar a los top-300 actores del gazetteer, pero son claramente relevantes para el análisis de cleavage.

---

## 5. Muestra de producción

La muestra de 80k artículos se genera con muestreo reproducible (`hash(article_id || seed)`):

```python
sample = load_political_articles(
    lake, gazetteer, lexicon=lexicon,
    year_range=(2019, 2022), min_actors=2, min_lexicon_hits=3,
    limit=80_000, seed=42
)
# → results/corpus/samples/political_2019_2022_80k.parquet
```

**Distribución de la muestra 80k:** 2019: 14.8k / 2020: 18.3k / 2021: 24.8k / 2022: 22.1k. Promedio 3.46 actores del gazetteer por artículo → contenido relacional denso.

**Costo estimado de extracción** (gemini-2.5-flash-lite, batch 50% descuento): ~$19–24 para 80k artículos (body mediana 551 tok, end2end = 2 llamadas: NER + relaciones).

---

## 6. Ventana temporal y justificación

Se elige **2019–2022** como ventana de máxima activación de cleavage en el Chile contemporáneo:

- **2019:** Estallido social (18-O) — movilización masiva, polarización aguda
- **2020:** Pandemia + plebiscito (78.3% apruebo) — crisis y consulta histórica
- **2021:** Convención constitucional + elección Boric/Kast (segunda vuelta) — eje izq/der más nítido
- **2022:** Gobierno de izquierda + segundo plebiscito (rechazo 62%) — consolidación y reversión

Ningún período posterior al estallido tiene densidad comparable para estudiar detección de clivaje con señal política clara.

---

*Implementación:* `text2sg/text2sg/corpus_data.py` — `build_gazetteer`, `build_political_lexicon`, `load_political_articles`. Tests: `text2sg/text2sg/tests/test_corpus_data.py` (12 tests, sin LLM, $0).
