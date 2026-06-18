# Dataset Schema

## Relations Format

Each relation in the gold standard represents a directed political action from one actor to another.

### Fields

```python
{
    "article_id": str,              # Unique article identifier (e.g., "emol_20150623_001")
    "from_entity": str,             # Actor who performs the action (e.g., "Gabriel Boric")
    "to_entity": str,               # Actor who receives the action (e.g., "Camila Vallejo")
    "act_type": str,                # Action type (one of: see below)
    "polarity": str,                # Sentiment: "positive" | "negative" | "neutral"
    "issue": str,                   # Topic domain (e.g., "fiscal_policy", "presidential_election")
    "evidence_quote": str,          # Exact substring from article (required for validation)
    "confidence": float,            # Ordinal: 1.0 (explicit), 0.7 (implied), 0.4 (speculative)
    "period": str,                  # Semester (e.g., "2015-H1")
}
```

### Action Types (act_type)

Nine relation types capture the political interaction space:

| act_type | Polarity | Example | Notes |
|---|---|---|---|
| **endorses** | + | "Boric apoyó la propuesta de Vallejo" | Support, backing |
| **attacks** | − | "Kast criticó fuertemente a la ministra" | Criticism, opposition |
| **allies_with** | + | "Firmaron un acuerdo conjunto" | Coalition, agreement |
| **calls_on** | ~ | "Le exigió al presidente que actuara" | Demand, request |
| **distances_from** | − | "Se desmarcó de la postura de su partido" | Public disagreement |
| **questions** | − | "Cuestionó la credibilidad del ministro" | Doubt, skepticism |
| **negotiates_with** | ~ | "Negoció con la oposición" | Dialogue, table talks |
| **competes_with** | − | "Compite directamente contra el candidato" | Rivalry |
| **accuses** | − | "Acusó de corrupción" | Criminal/ethical charge |

### Polarity

- **positive** (+): Supportive, collaborative, endorsing
- **negative** (−): Oppositional, critical, conflictual
- **neutral** (~): Factual interaction without clear valence (calls_on, negotiates_with, competes_with default to neutral unless context says otherwise)

### Confidence Levels

Annotators mark confidence to distinguish explicit mentions from inferred relations:

| confidence | Definition | Example |
|---|---|---|
| 1.0 | **Explicit** — clear statement in text | "Boric respaldó" (text says "endorses") |
| 0.7 | **Implied** — requires inference from context | "Boric asistió a la marcha de Vallejo" → implies endorsement |
| 0.4 | **Speculative** — plausible but not stated | "ambos son de izquierda" → may imply alliance (weak signal) |

**Default filter:** Use confidence ≥ 0.7 for strict evaluation; include 0.4 for exploratory analysis.

---

## Articles Format

### Raw (CSV)

```
article_id,outlet,date,headline,body,url,author
emol_20150623_001,Emol,2015-06-23,"Boric respaldó...",Lorem ipsum...,https://emol.cl/...,Anonymous
```

### Processed (Parquet)

```python
{
    "article_id": str,
    "outlet": str,              # News source (la_tercera, emol, mostrador, ...)
    "date": str,                # ISO 8601 (YYYY-MM-DD)
    "period": str,              # Semester computed from date (e.g., "2015-H1")
    "headline": str,
    "body": str,                # Full text, cleaned
    "body_tokens": int,         # Token count
    "url": str,
    "author": str,              # May be null
    "topics": list[str],        # BERT topic labels (if available)
}
```

### Entity Unions (JSON)

Pre-computed actor lists for each article (used in `given_entities` mode extraction):

```json
{
    "article_id": "emol_20150623_001",
    "actors": {
        "U1": {
            "canonical_name": "Gabriel Boric",
            "canonical_names": ["Gabriel Boric", "Boric", "el diputado Boric"],
            "type": "roster_actor",  // politician, party, ministry, journalist, etc.
            "aliases": ["Boric", "Gabriel"]
        },
        "U2": {
            "canonical_name": "Camila Vallejo",
            "canonical_names": ["Camila Vallejo", "Vallejo", "la ministra Vallejo"],
            "type": "roster_actor",
            "aliases": ["Vallejo"]
        }
    }
}
```

---

## Splits (train/val/test)

Located in `data/gold/splits.json`:

```json
{
    "train": ["article_id_001", "article_id_002", ...],  # 60%
    "val": ["article_id_250", ...],                       # 20%
    "test": ["article_id_500", ...]                       # 20%
}
```

**Stratification:** Splits maintain:
- Temporal balance (each semester represented)
- Outlet balance (each news source proportional)
- Actor diversity (no single politician dominates any split)

---

## Quality Metrics

### Inter-rater Agreement

When >1 annotator labeled the same articles:

- **κ (Cohen's kappa):** 0.82 (substantial agreement)
- **Fleiss' κ:** 0.79 (when 3+ raters)
- **Boundary disputes:** Disagreements mostly on confidence level (0.7 vs 1.0), not relation existence

### Coverage Issues

- **False positives in gold:** ~3% (LLM over-prediction that annotators kept as valid)
- **False negatives in gold:** ~18% (omissions by annotators on skipped articles or dense sections)
- **Weak labels:** ~18% of articles have algorithmic pre-labels (auto-generated, lower confidence, filtered to confidence ≥ 0.7)

---

## Known Limitations

1. **Bias towards formal register** — Informal/colloquial speech underrepresented
   - Impact: Model trained on this may underperform on Twitter/informal text
2. **Coverage by outlet** — La Tercera, Emol dominate; smaller outlets less present
   - Impact: Elite networks from these outlets are better represented
3. **Actor coverage** — Prominent politicians (presidential level) over-represented
   - Impact: Local/regional actors undersampled
4. **Time period gaps** — 2015–2016 ("Dirty period") and 2019-H2 ("Social outbreak") have noisier labels
   - Impact: Use with caution; see QUALITY.md for details
5. **Directionality inference** — Passive voice ("fue criticado por X") requires inference to flip direction
   - Impact: Confidence ≤ 0.7 when inference required; test carefully

---

## Examples

### Example 1: Simple Endorsement

```json
{
    "article_id": "mostrador_20200301_045",
    "from_entity": "Gabriel Boric",
    "to_entity": "Beatriz Sánchez",
    "act_type": "endorses",
    "polarity": "positive",
    "issue": "presidential_election",
    "evidence_quote": "Boric respaldó la candidatura de Beatriz Sánchez",
    "confidence": 1.0,
    "period": "2020-H1"
}
```

### Example 2: Inferred Attack

```json
{
    "article_id": "tercera_20160415_201",
    "from_entity": "Pablo Longuería",
    "to_entity": "Raúl Saldívar",
    "act_type": "questions",
    "polarity": "negative",
    "issue": "government_management",
    "evidence_quote": "Longuería cuestionó severamente la gestión del intendente",
    "confidence": 0.7,
    "period": "2016-H1"
}
```

### Example 3: Coalition Negotiation

```json
{
    "article_id": "emol_20180927_089",
    "from_entity": "Nueva Mayoría",
    "to_entity": "Convergencia Social",
    "act_type": "negotiates_with",
    "polarity": "neutral",
    "issue": "political_coalitions",
    "evidence_quote": "Los bloques negociaron espacios para las próximas elecciones",
    "confidence": 1.0,
    "period": "2018-H2"
}
```

---

## Validation Rules

When loading/ingesting relations, validate:

✅ **Schema compliance:**
- All required fields present
- act_type in {endorses, attacks, allies_with, calls_on, distances_from, questions, negotiates_with, competes_with, accuses}
- polarity in {positive, negative, neutral}
- confidence in [0.0, 1.0]

✅ **Semantic consistency:**
- evidence_quote is a substring of the article body
- evidence_quote ≥ 8 characters (to avoid trivial matches)
- from_entity and to_entity are distinct (no self-loops)

✅ **Temporal:**
- date is a valid ISO 8601 date
- period can be computed from date (period = YYYY-H1 or YYYY-H2)

See `scripts/validate.py` for implementation.
