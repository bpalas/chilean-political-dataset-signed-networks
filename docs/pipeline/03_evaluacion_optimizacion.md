# Evaluación y Optimización del Extractor

> Sección de paper: **§ Metodología — Benchmark y optimización evolutiva**

---

## 1. El problema de evaluación con gold real

El gold real de extracción tiene una tasa de omisión del ~29%: el 29% de los "falsos positivos" son en realidad relaciones verdaderas que el anotador humano no incluyó. Esto hace que cualquier optimizador que use el gold real *degrade* el extractor (el optimizador aprende a callar donde hay incertidumbre del gold, no donde no hay evidencia).

Solución: **gold sintético 100% controlado** — artículos generados con relaciones plantadas explícitamente. El optimizador sabe exactamente qué debe extraer; toda desviación es error medible del extractor.

---

## 2. Gold sintético v2

**Dataset v2:** 287 artículos sintéticos de noticias chilenas con 914 relaciones plantadas.

| Subconjunto | N artículos | Relaciones | Generador |
|---|---|---|---|
| v1 (base) | 200 | ~680 | Opus 4.x |
| Adición v2 | 87 | ~234 | Opus 4.8 / Fable 5 |
| **Total v2** | **287** | **914** | — |

**Características del gold v2:**
- Columna `difficulty` (1–10): gradiente de dificultad de extracción
- Columna `writer` (opus-4.8 / fable-5): para análisis de sesgos del generador
- Columna `medio`: outlet real del que imita el estilo (biobio, latercera, etc.)
- Split estratificado por `domain × registro`: `text2sg/results/synthetic/v2/split.json`

**Debilidades conocidas del sintético:**
- Fútbol: P=0.435 (el extractor confunde conflictos deportivos con políticos)
- Coloquial: P=0.606 (lenguaje informal → mayor tasa de abstención incorrecta)

---

## 3. Métricas de evaluación

### Métricas principales

**f0.5** (harmonic mean con β=0.5 → peso 2× precisión):
```
f0.5 = (1 + 0.5²) × P × R / (0.5² × P + R)
```

Se usa f0.5 (no f1) porque en el caso de uso real (análisis de redes signadas) un falso positivo contamina el grafo con una arista incorrecta, mientras un falso negativo solo omite información. El costo asimétrico justifica precision-first.

**P/R directed vs undirected:**
- **Directed:** `(A apoya B)` ≠ `(B apoya A)` — la dirección importa
- **Undirected:** `{A, B}` → par de actores (ignora dirección) — señal más robusta
- **Gap directed−undirected:** cuánto pierde el extractor por errores de dirección

### Función de selección (`selection_score`)
```
score = f0.5
      - penalty_distractor_fp × n_distractor_fp    # actores señuelo inventados
      - max(0, recall_floor - R) × recall_penalty  # piso de recall (0.80)
```

El "piso de recall" (0.80) asegura que la optimización precision-first no colapsa el recall. Los distractores (actores que aparecen en el artículo pero NO tienen relaciones plantadas) miden la tasa de alucinación pura.

### Gradientes multi-dimensionales

El frente de Pareto mantiene 5 gradientes independientes:
1. **precision** (`act_type`, `polarity`, `issue`) — calidad de la etiqueta
2. **recall** — cobertura de las relaciones gold
3. **directed** — captura correcta de la dirección
4. **undirected** — cobertura sin importar dirección
5. **distractor_fp** — resistencia a actores señuelo

---

## 4. Frente de Pareto y loop evolutivo (GEPA)

El optimizador mantiene un **frente de Pareto multi-gradiente** donde cada genoma puede dominar en una dimensión y ser dominado en otra. No hay "un ganador único" sino un archivo de especializaciones.

### Selección (GEPA win-count)
El padre para cada mutación se selecciona por **win-count**: cuántas comparaciones 1-vs-1 gana el genoma en el conjunto de artículos de evaluación. Esto favorece genomas robustos (no los que sobreajustan a un subconjunto).

### Loop de un ciclo
```
1. pick(select=gepa)    → padre + diagnóstico (FP/FN por tipo de artículo)
2. propose/cross/fresh  → mutación de UN artefacto (A, B, o C; nunca dos)
3. synth_run_model.py   → evaluación sobre gold v2 (n=207 artículos del split train)
4. add --parent <id>    → registrar en frente
5. [opcional] merge     → combinar componentes complementarios de dos genomas
```

### Panel de propuesta (gepa_panel_loop)
Para salir de óptimos locales, 4 agentes proponen en paralelo con lentes distintos:
- **recall-hunter:** maximiza cobertura (mira FN del diagnóstico)
- **precision-hawk:** maximiza precisión (mira FP y distractores)
- **direction-fixer:** reduce gap directed−undirected
- **fresh-architect:** propone desde cero sin ver el historial

Un **combinador** (estratega CROSS) sintetiza las propuestas viendo el board de scores por mutación → inyecta las fortalezas complementarias por componente (merge selectivo).

---

## 5. Historial de optimización

| Genoma | Método | f0.5 | P | R | Distractores FP |
|---|---|---|---|---|---|
| id1 (baseline) | prompt manual | ~0.86 | ~0.90 | ~0.75 | — |
| id3 | loop QD iter1 | 0.894 | — | — | — |
| **id15 (campeón)** | **mutación manual (usuario)** | **0.928** | **0.940** | **0.884** | **3** |

**Hallazgo clave:** id15 fue generado con ideas del usuario (no del optimizador autónomo). Los 2 cuellos identificados del self-evolve son:
1. **Creatividad de Opus:** los propuestas autónomas eran variaciones menores, no saltos
2. **Falta de feedback de scores por mutación:** el combinador no veía qué dimensión mejoró qué mutación

Ambos cuellos están resueltos en el `gepa_panel_loop.workflow.js` (panel + board).

---

## 6. Alineación con el gold real de la tesis

La tesis usa el extractor anterior (pipeline congelado en `clivaje-evolve/src/`) con validación spot-check:
- **Polarity accuracy:** 0.89 (83/83 relaciones sin inversión de signo)
- Dataset: 64k artículos de 2014–2026

text2graph-evolve mejora la precisión de extracción de f0.5 ~0.86 (baseline) a **0.928** (id15), medida sobre el gold sintético v2. La validación cruzada con el gold real compartido (artículos del mismo corpus) es el gate de calidad antes del run de 80k (F7 del roadmap).

---

*Implementación:* `text2sg/text2sg/pareto.py` (frente), `text2sg/text2sg/fitness.py` (selection_score), `text2sg/text2sg/rubric.py` (métricas P/R/directed), `text2sg/text2sg/mutate.py` (merge/cross/fresh). CLI: `text2sg/scripts/synth_evolve.py`.
