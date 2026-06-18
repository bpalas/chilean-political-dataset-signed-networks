# Alineación con la Tesis MSc y Hoja de Ruta del Paper 2

> Documento de orientación — no va al paper directamente, es contexto de decisión.

---

## Estado actual (2026-06-17)

### La tesis (tesis-msc-datascience): DEFENDIBLE HOY

La tesis estudia la **estructura de clivaje en la élite política chilena** via redes signadas.

| Aspecto | Estado |
|---|---|
| Capítulos | ✅ 8/8 redactados |
| Hallazgos centrales | ✅ Con números (tabla abajo) |
| Validación de extracción | ✅ Apéndice 03 (polarity acc 0.89, 83/83 sin inversión de signo) |
| Pendiente crítico | PDF compilado + ref VALPOP + decisión §3 (PCD vs C+ light) |

**Hallazgos centrales de la tesis:**

| Hallazgo | Evidencia |
|---|---|
| Núcleo organizador ≠ figuras presidenciales | Boric 22/25 periodos como objeto; núcleo 10× más denso |
| p_norm resuelve confundido con grado | crudo r=0.96 con grado → normalizado r=−0.32 |
| Eje como atractor temático | Align_T=0.68 vs 0.50 null, p<0.001, 16/16 temas sobre azar |
| Estabilidad a través del estallido | r̄=0.72; mínimo en transición electoral 2016-17, no 2019 |

**Corpus de la tesis:** 64k artículos (2014–2026), 289,805 aristas signadas, 25 cortes semestrales. Pipeline congelado en `clivaje-evolve/src/`.

---

## Relación entre repos

```
tesis-msc-datascience/   ← paper de ANÁLISIS (redes signadas, clivaje, métricas)
    └── usa extractor de clivaje-evolve/src/ (pipeline congelado)

clivaje-evolve/          ← ANÁLISIS + track evolutivo de algoritmos de grafo
    └── src/             ← CONGELADO — reproduce los resultados de la tesis
    └── tesisv2/evolve/  ← paper 3: hallazgo algorítmico generalizable (KDD/WWW)

text2graph-evolve/       ← PAPER 2: extractor mejorado a escala
    └── mejora el extractor de clivaje/src/ (f0.5 0.86 → 0.928)
    └── escala 64k → 80k → 383k → 4.88M artículos
    └── Batch API + DuckDB + Entity Resolution
```

---

## Paper 2: qué aporta text2graph-evolve

### Claim central del paper 2
*Un extractor de relaciones políticas signadas optimizado evolutivamente (text2SG v2) escala de ~64k a 383k artículos de noticias chilenas, manteniendo f0.5 ≥ 0.91 y habilitando análisis longitudinal de mayor resolución temporal.*

### Secciones del paper 2 → docs del pipeline

| Sección del paper | Documento |
|---|---|
| **§ Datos** — Corpus, prefiltro político, muestra | [`01_corpus_prefiltro.md`](01_corpus_prefiltro.md) |
| **§ Metodología** — Pipeline de extracción, genoma | [`02_extraccion.md`](02_extraccion.md) |
| **§ Evaluación** — Gold sintético, Pareto, loop | [`03_evaluacion_optimizacion.md`](03_evaluacion_optimizacion.md) |
| **§ Escala** — Batch API, ER, storage, validación | [`04_escala_storage.md`](04_escala_storage.md) |

---

## Año y ventana temporal

**Estamos en 2026.** El corpus cubre 2014–2026.

La ventana elegida para paper 2 es **2019–2022** por ser el período de máxima activación de cleavage en el Chile contemporáneo:

```
2019  estallido social (18-O)           → movilización masiva, polarización aguda
2020  pandemia + plebiscito (apruebo)   → crisis + consulta histórica
2021  convención + elección Boric/Kast  → eje izq/der más nítido desde 1989
2022  gobierno Boric + rechazo          → consolidación y primera reversión
```

Densidad política: 383,675 artículos pre-filtrados (gazetteer + léxico) → suficiente para 80k muestra con alta densidad relacional (promedio 3.46 actores mencionados por artículo).

---

## ¿Están alineados?

**Sí, en capas distintas sin solapamiento:**

- La **tesis** cierra ahora con el extractor viejo (f0.5 ~0.86) y el corpus de 64k. El paper 2 no invalida ni modifica la tesis — la extiende con mejor extractor y mayor escala.

- **text2graph-evolve** (paper 2) = metodología de extracción + benchmark sintético + optimización evolutiva + escala. Los hallazgos de red (p_norm, Align_T, estabilidad) son de la tesis; el paper 2 los usa como motivación pero su contribución es la *extracción y la escala*.

- **clivaje-evolve/tesisv2** (paper 3 futuro) = si el loop evolutivo descubre un algoritmo de grafo generalizable que gane en benchmarks públicos (Congress, Wikipedia RfA, Slashdot) → KDD/WWW. Independiente del extractor.

**La cadena es:** tesis (análisis) → paper 2 (extractor + escala) → paper 3 (algoritmo generalizable). Cada uno se sostiene solo.

---

## Lo que queda para defender la tesis (urgente)

Del ROADMAP de tesis-msc-datascience:

**Críticos (bloquean defensa):**
1. Compilar PDF y verificar refs cruzadas (Apéndice 03 ↔ `\ref{app:validacion}`)
2. Agregar referencia VALPOP (Solovev & Lasser) a `citas.bib`
3. Revisar prosa editada en Cap 4/7/8
4. Decisión §3 con supervisores: C (PCD sin FAULTANA) vs C+ light (SPONGE benchmark)

**Lo que NO entra a la tesis (disciplina de alcance):**
- El track evolutivo de text2graph-evolve → mención en "trabajo futuro", no en resultados
- La escala a 80k/383k → trabajo futuro
- La mejora del extractor a f0.5 0.928 → no invalida el Apéndice 03 existente (0.89 polarity acc es sobre el extractor de la tesis, no del paper 2)
