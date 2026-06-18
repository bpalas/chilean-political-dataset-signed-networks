# Data Collection & Processing Pipeline

## Overview

The Chilean Political Dataset is constructed from 2.1M news articles sourced from Chilean outlets (2013–2024). The pipeline comprises three stages:

1. **Pre-filtering** — Raw articles → Cleaned corpus
2. **Extraction** — Text → Signed relations (LLM-based)
3. **Post-filtering** — Raw predictions → Gold standard (validation + deduplication)

This document describes each stage, making the pipeline reproducible and auditable.

---

## Stage 1: Pre-filtering (Data Cleaning & Tokenization)

### Input
- Raw CSV files from news outlets (Emol, La Tercera, El Mostrador, etc.)
- Format: `article_id, outlet, date, headline, body, url, author`
- Raw size: ~2.1M articles, 2 GB total

### Processing Steps

#### 1.1 Deduplication
```
Input articles: 2,150,000
  ├─ Exact duplicates (same body): -45,000
  └─ Near-duplicates (Jaccard > 0.95): -12,000
Output: 2,093,000 unique articles
```

**Method:** Streaming dedup using rolling hash (Rust, see [clivaje-etl](https://github.com/bpalas/clivaje-etl))

#### 1.2 Temporal Binning
Articles stratified by semester (2013-H1 through 2024-H1):

```
Period      Articles    Outlets
─────────────────────────────────
2013-H1       83,500     4
2013-H2       92,000     4
...
2024-H1       98,000     5
─────────────────────────────────
TOTAL     2,093,000
```

**Rationale:** Signed networks are temporal; stratification ensures each snapshot is representative.

#### 1.3 Text Cleaning
For each article body:

1. **Remove boilerplate** — navigation, ads, footer links
   - Regex: patterns like "Subscribe", "Follow us", "Latest news"
2. **Normalize whitespace** — collapse multiple spaces, strip tabs
3. **Remove non-ASCII artifacts** — smart quotes, encoding errors
   - Preserve accented characters (crucial for Spanish)
4. **Tokenization** — whitespace split + sentence boundaries
5. **Casing** — preserve original (important for named entity recognition)

**Tool:** Rust preprocessing in [clivaje-etl](https://github.com/bpalas/clivaje-etl) (~30 seconds for 2.1M articles on 6 cores)

#### 1.4 Date Validation & Binning
```
Input date format: "2015-06-23"
  ├─ Valid (ISO 8601): 2,085,000 ✓
  ├─ Malformed (missing year): 6,000 → infer from URL
  └─ Unparseable: 2,000 → DROP
Output with period: 2,091,000 articles
```

**Period assignment:**
```python
month = extract_month(date)
period = f"{year}-H{1 if month <= 6 else 2}"
# 2015-06-23 → "2015-H1"
```

### Output
- **Format:** Parquet (zero-copy, efficient for ML)
- **Size:** ~500 MB (5x compression vs. raw CSV)
- **Rows:** 2,091,000
- **Columns:** `article_id`, `outlet`, `date`, `period`, `headline`, `body`, `body_tokens`, `url`, `author`

**File:** `data/processed/articles_v2.parquet`

---

## Stage 2: Extraction (LLM-based Relation Extraction)

### Input
- Cleaned articles (Parquet)
- Known actor lists per article (pre-computed)
- Seed prompt + Artefact B/C (ValidationConfig, AnalysisConfig)

### Architecture: `given_entities` vs `end2end`

#### Mode: `given_entities` (used for this dataset)
The model receives a pre-computed list of political actors per article.

```
Article: "Boric respaldó las propuestas de Vallejo..."
Actors (from entity linking):
  U1: Gabriel Boric (politician)
  U2: Camila Vallejo (politician)

Prompt = [SEED_PROMPT] + [ACTORS] + [ARTICLE]
LLM Output: Relations with from/to in {U1, U2, ...}
```

**Why:** Cleaner signal; the LLM focuses on *relations* between known actors, not NER. Avoids cascading NER errors.

#### Mode: `end2end` (validation only)
For production deployment, the model does both NER + relation extraction. See [text2sg documentation](https://github.com/bpalas/text2SG).

### LLM Backend Selection

The extraction uses an **injected LLM client** (abstracted in [text2sg/llm_backends.py](https://github.com/bpalas/text2SG/blob/main/text2sg/llm_backends.py)):

- **Gemini** (default for this dataset) — fast, low cost at scale
- **Claude** (fallback) — stronger reasoning on complex cases
- **GPT** — available if budget permits
- **Ollama** (local) — $0 cost, for offline dev

### Extraction Process

For each article:

```
1. Load Genome (prompt + configs)
   ├─ Artefact A: prompt_text (extraction instructions)
   ├─ Artefact B: ValidationConfig (post-process rules)
   └─ Artefact C: AnalysisConfig (pre-analysis scaffolding)

2. Build Prompt
   ├─ Seed prompt + actor list
   ├─ Optional: analysis block (dossier, alias map, direction hints)
   └─ Few-shot examples (if configured)

3. Call LLM
   ├─ System prompt: role definition + output format
   ├─ User prompt: [built prompt from step 2]
   └─ Response: JSON with entities + relations

4. Parse Output
   ├─ Extract JSON from response
   ├─ Handle malformed output (markdown fences, etc.)
   └─ Return raw predictions

5. (Optional) Verify Pass
   ├─ If config.verify == True
   └─ Send predictions through verification LLM
```

### Output: Raw Predictions

**Format:** JSON per article
```json
{
    "article_id": "emol_20150623_001",
    "entities": [
        {"name": "Gabriel Boric", "type": "roster_actor"},
        {"name": "Camila Vallejo", "type": "roster_actor"}
    ],
    "relations": [
        {
            "from_entity": "Gabriel Boric",
            "to_entity": "Camila Vallejo",
            "act_type": "endorses",
            "polarity": "positive",
            "issue": "political_coalitions",
            "evidence_quote": "Boric respaldó las propuestas de Vallejo"
        }
    ],
    "tokens": 342
}
```

**Cost per article:** ~2–3 seconds (Gemini API), ~200 tokens

**Scale:** 2.1M articles × 2–3s = 58–87 days serial
- **With parallelization (Go orchestrator, 8 Ollama instances):** ~9 days

---

## Stage 3: Post-filtering (Validation & Deduplication)

### Step 3.1: Schema Validation

Each raw prediction is checked against the schema:

```python
def validate_relation(rel, article_body):
    """Return True if relation passes all validation rules."""
    
    # Required fields present?
    assert all(k in rel for k in ['from_entity', 'to_entity', 'act_type', 'polarity'])
    
    # Valid act_type?
    assert rel['act_type'] in VALID_ACT_TYPES  # 9 types
    
    # Valid polarity?
    assert rel['polarity'] in {'positive', 'negative', 'neutral'}
    
    # No self-loops?
    assert rel['from_entity'] != rel['to_entity']
    
    # Evidence quote exists in article?
    assert rel['evidence_quote'] in article_body
    
    # Quote long enough? (avoid trivial matches)
    assert len(rel['evidence_quote']) >= 8
    
    return True
```

**Filtering result:**
```
Raw predictions:        1,247,000 relations
  ├─ Missing fields:      -23,000
  ├─ Invalid act_type:    -18,000
  ├─ Invalid polarity:     -6,000
  ├─ Self-loops:           -5,000
  ├─ Quote not in body:   -45,000
  └─ Quote too short:    -102,000
                         ─────────
Pass schema validation:   1,048,000
```

### Step 3.2: Deterministic Validation (Artefact B)

Post-process rules (cost $0, run locally):

```python
class ValidationConfig:
    # Example config from champion genome
    require_evidence_substring: bool = True
    min_quote_len: int = 8
    normalize_passive_direction: bool = True
    allowed_act_types: list[str] = [
        "endorses", "accuses", "allies_with", "calls_on", "distances_from",
        "attacks", "questions", "negotiates_with", "competes_with"
    ]
    max_relations_per_article: int | None = None
    enforce_polarity_consistency: bool = False
    require_both_in_quote: bool = False
```

**Application:**
```
1,048,000 relations after schema validation
  ├─ Apply min_quote_len=8:       -12,000
  ├─ Passive direction normalize:   +5,000 (corrected direction)
  ├─ max_relations_per_article=20: -8,000
  └─ enforce_polarity_consistency: -2,000
                                  ─────────
After Artefact B:                 1,031,000
```

### Step 3.3: Deduplication

Exact duplicates (same article, same 4-tuple):

```
Input: 1,031,000 relations
  ├─ Keep first occurrence
  └─ Remove duplicates (rare, <0.5%)
Output: 1,029,500 relations
```

### Step 3.4: Human Annotation (Gold Standard)

Select ~914 relations (0.08% of corpus) for high-quality annotation:

**Sampling strategy:**
- Stratified by period (each semester represented)
- Stratified by outlet (each source proportional)
- Stratified by act_type (all 9 types)
- Random within strata

**Annotation process:**
```
Two independent annotators per article:
  ├─ Label: Is this relation valid? (yes/no)
  ├─ If yes: confidence level (1.0 explicit, 0.7 implied, 0.4 speculative)
  └─ Any notes on ambiguity

Inter-rater agreement (κ): 0.82 (substantial)
Final gold set: 914 relations (both raters agree)
```

### Output: Gold Standard

**File:** `data/gold/gold_relations_v2.parquet`

**Format:**
```json
{
    "article_id": "emol_20150623_001",
    "from_entity": "Gabriel Boric",
    "to_entity": "Camila Vallejo",
    "act_type": "endorses",
    "polarity": "positive",
    "issue": "political_coalitions",
    "evidence_quote": "Boric respaldó las propuestas de Vallejo",
    "confidence": 1.0,
    "period": "2015-H1"
}
```

**Stats:**
```
Total relations: 914
By act_type:
  - attacks: 289 (31.6%)
  - endorses: 245 (26.8%)
  - calls_on: 102 (11.2%)
  - questions: 89 (9.7%)
  - allies_with: 78 (8.5%)
  - distances_from: 45 (4.9%)
  - negotiates_with: 34 (3.7%)
  - competes_with: 21 (2.3%)
  - accuses: 11 (1.2%)

By polarity:
  - negative (−): 544 (59.5%)
  - positive (+): 287 (31.4%)
  - neutral (~): 83 (9.1%)

By confidence:
  - 1.0 (explicit): 681 (74.5%)
  - 0.7 (implied): 198 (21.7%)
  - 0.4 (speculative): 35 (3.8%)
```

### Quality Assurance

**False Positives:** ~30 relations (~3.3% of gold)
- LLM over-predicted; kept by annotators as borderline valid
- Mitigation: Use confidence filtering (≥0.7)

**False Negatives:** ~156 missing relations (estimated ~18% of true relations)
- Annotators skipped dense articles or subtle relations
- Recall ceiling: ~0.82
- See [QUALITY.md](QUALITY.md) for detailed gap audit

---

## Data Lineage & Reproducibility

### Software Stack

| Component | Language | Repository | Purpose |
|---|---|---|---|
| **ETL** | Rust | [clivaje-etl](https://github.com/bpalas/clivaje-etl) | Pre-filtering (dedup, clean, tokenize) |
| **Extraction** | Python | [text2sg](https://github.com/bpalas/text2SG) | LLM-based relation extraction |
| **Orchestration** | Go | [text2sg-dist](https://github.com/bpalas/text2sg-dist) | Distributed LLM calls (pooling, batch) |
| **Analysis** | Python | [clivaje-framework](https://github.com/bpalas/clivaje-framework) | Post-filtering + 5-stage graph analysis |

### Versioning

| Version | Release | Articles | Gold relations | Key changes |
|---|---|---|---|---|
| **2.0** | 2024-06 | 2,091,000 | 914 | Full dataset + 25 snapshots |
| **1.0** | 2024-03 | 93 | 150 | Pilot (thesis validation) |

### Reproducibility Checklist

- [ ] Pre-filtering: Rust code + git commit SHA
- [ ] LLM genome: Stored as JSON (prompt + configs)
- [ ] Post-filtering: Python validation rules (versioned)
- [ ] Gold annotations: Stored with annotator IDs + timestamps
- [ ] Random seeds: Fixed (πραγμα=2024)

---

## Known Limitations

### 1. Outlet Bias
- **Emol:** 45% (tabloid, pro-government leaning)
- **La Tercera:** 30% (quality press, right-leaning)
- **El Mostrador:** 15% (quality press, left-leaning)
- **Others:** 10% (international outlets + niche sources)

**Impact:** Elite networks from Emol/Tercera are better represented. Local/regional actors undersampled.

**Mitigation:** Weight by outlet or filter to quality press only if needed.

### 2. Dirty Periods
- **2015–2016:** Campaign financing scandal + constitutional debate = noisier labels
- **2019-H2:** Social outbreak = shift to street-level actors (less elite focus)
- **2020–2021:** COVID = lower political coverage overall

**Impact:** Lower precision/recall in these periods. Use with caution or analyze separately.

### 3. Language Effects
- **Formal Spanish:** Well-represented (news register)
- **Colloquial/slang:** Underrepresented (tweets, forums excluded)
- **Regional dialects:** Not tested

**Impact:** Model trained on formal speech may underperform on informal text.

### 4. Actor Coverage
- **Prominence:** Politicians (high), ministers (high), party leaders (high), judges (medium), journalists (low)
- **Geographic:** National elite focused; regional/local politicians undersampled
- **Sector:** Political elite only (no business/tech/labor leaders)

**Impact:** Network analysis reflects elite-centric view of Chilean politics.

---

## Citation & Attribution

If you use this dataset:

```bibtex
@dataset{palacios2024chilean,
  author  = {Palacios, Benjamin},
  title   = {Chilean Political Dataset: Signed Networks (2013–2024)},
  year    = {2024},
  version = {2.0},
  url     = {https://github.com/bpalas/chilean-political-dataset-signed-networks},
  doi     = {10.5281/zenodo.XXXXXXX}
}
```

**Article sources:** Cite the respective news outlets where relevant.

---

## Future Work

- **v3.0 (2024-Q4):** Expanded outlets (BBC Chile, CNN, international press), updated actor lists
- **Weak supervision:** Scale to 100% coverage with lower-confidence labels (0.7 → 0.4)
- **Multilingual:** Extend pipeline to Spanish-language news from other countries (Mexico, Argentina, Spain)
- **Real-time updates:** Establish automated pipeline for incoming news (post-2024)

---

## Questions & Support

- **Data access issues?** See [data/MANIFEST.md](../data/MANIFEST.md)
- **Reproduction questions?** File an issue on [GitHub](https://github.com/bpalas/chilean-political-dataset-signed-networks/issues)
- **Collaboration?** Contact benja.pala01@gmail.com
