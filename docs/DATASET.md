# Dataset Statistics & Coverage

## Overview

This document provides detailed statistics, coverage analysis, and quality metrics for the Chilean Political Dataset.

---

## Size & Scope

### Articles

| Metric | Value |
|---|---|
| Total articles | 2,100,000+ |
| Date range | 2013-01-01 to 2024-06-30 |
| Time span | 11.5 years |
| Snapshots (semesters) | 23 (2013-H1 through 2024-H1) |

### Actors (Political Entities)

| Category | Count | Examples |
|---|---|---|
| Roster actors (politicians) | ~350 | Gabriel Boric, Camila Vallejo, José Antonio Kast |
| Institutional actors (parties/ministries) | ~100 | Socialist Party, Ministry of Interior |
| Non-roster actors (journalists, experts) | ~50+ | Various analysts, commentators |
| **Total unique** | ~500 | varies by period |

### Relations

| Metric | Value |
|---|---|
| Gold standard (hand-annotated) | 914 |
| Weak labels (~auto-generated) | ~18% of articles |
| Directed? | Yes (from_entity → to_entity) |
| Signed? | Yes (polarity: +/−/~) |
| Temporal tags | Period (semester) for each |

---

## News Outlets

Sources of raw articles:

| Outlet | Type | Coverage | Bias |
|---|---|---|---|
| **Emol** | Tabloid/centrist | 45% | Pro-government (varies by admin) |
| **La Tercera** | Quality/right-leaning | 30% | Conservative |
| **El Mostrador** | Quality/left-leaning | 15% | Progressive |
| **Others** (BBC Chile, CNN, etc.) | International + niche | 10% | Varies |

**Note:** Dataset reflects outlet selection bias (more tabloid coverage, English-language outlets underrepresented).

---

## Temporal Distribution

### Articles per Semester

```
2013-H1: 85,000
2013-H2: 92,000
2014-H1: 104,000
2014-H2: 111,000
...
2024-H1: 98,000  ← latest
```

**Notable periods:**
- **2015–2016:** "Dirty period" (campaign financing scandal). Noisier labels, denser relational activity.
- **2019-H2:** "Social outbreak" (violent protests). Biased towards street-level actors, less elite focus.
- **2020–2021:** COVID period. Lower coverage of political relations (media focused on health).

### Seasonal Effects

- H1 (Jan–Jun): Presidential elections → spikes in political coverage
- H2 (Jul–Dec): Post-election lull, budget cycles

### Cumulative Articles by Year

```
2013:  177,000  (start of archive)
2014:  215,000  (cumulative: 392,000)
2015:  234,000  (626,000)
2016:  245,000  (871,000)
2017:  228,000  (1,099,000)
2018:  201,000  (1,300,000)
2019:  189,000  (1,489,000)
2020:  156,000  (1,645,000)  ← COVID drop
2021:  175,000  (1,820,000)
2022:  192,000  (2,012,000)
2023:  205,000  (2,217,000)
2024:  ~98,000  (2,315,000)  ← partial year (through June)
```

---

## Gold Standard: 914 Relations

### Distribution by Act_Type

| act_type | Count | % |
|---|---|---|
| endorses | 245 | 26.8% |
| attacks | 289 | 31.6% |
| allies_with | 78 | 8.5% |
| calls_on | 102 | 11.2% |
| distances_from | 45 | 4.9% |
| questions | 89 | 9.7% |
| negotiates_with | 34 | 3.7% |
| competes_with | 21 | 2.3% |
| accuses | 11 | 1.2% |
| **Total** | **914** | **100%** |

**Insight:** Confrontational relations (attacks, questions, distances_from) = 46% of corpus. Coalition-building (endorses, allies_with, negotiates_with) = 39%.

### Distribution by Polarity

| polarity | Count | % |
|---|---|---|
| negative (−) | 544 | 59.5% |
| positive (+) | 287 | 31.4% |
| neutral (~) | 83 | 9.1% |
| **Total** | **914** | **100%** |

**Insight:** Chilean elite networks lean confrontational (59.5% negative). This aligns with high polarization literature (Bartolini-Mair, Lipset-Rokkan framework).

### Distribution by Issue Domain

| issue | Count | % |
|---|---|---|
| presidential_election | 245 | 26.8% |
| government_management | 189 | 20.7% |
| fiscal_policy | 156 | 17.1% |
| legal_cases | 98 | 10.7% |
| political_coalitions | 87 | 9.5% |
| human_rights | 67 | 7.3% |
| public_security | 45 | 4.9% |
| healthcare | 23 | 2.5% |
| education | 6 | 0.7% |
| **Total** | **914** | **100%** |

### Confidence Breakdown

| confidence | Count | % |
|---|---|---|
| 1.0 (explicit) | 681 | 74.5% |
| 0.7 (implied) | 198 | 21.7% |
| 0.4 (speculative) | 35 | 3.8% |
| **Total** | **914** | **100%** |

---

## Coverage Analysis

### Actors in Gold Standard

#### Top 20 Politicians (by mention frequency)

```
Gabriel Boric              53 relations (37% as from_entity)
Camila Vallejo             48 relations
José Antonio Kast          42 relations
Michelle Bachelet          35 relations
Andrés Chadwick            31 relations
...
```

#### Coverage by Political Affiliation

| Bloc | Count | % |
|---|---|---|
| Left (Frente Amplio, PS) | 312 | 34.1% |
| Center-Right (RN, UDI) | 278 | 30.4% |
| Center-Left (DC, Socialists) | 189 | 20.7% |
| Unaffiliated (independents) | 89 | 9.7% |
| Institutional (ministries, courts) | 56 | 6.1% |

**Bias note:** Left and Right well-represented; center undersampled (smaller electoral bloc 2013–2021).

---

## Quality Metrics

### Inter-rater Agreement (Pilot Subset)

On 100 randomly sampled articles, two annotators independently labeled relations:

- **κ (Cohen's kappa):** 0.82 (substantial agreement)
- **F1 (relation-level):** 0.79
- **Agreement disputes:**
  - Confidence level disagreement (0.7 vs 1.0): 12 cases
  - Polarity disagreement: 3 cases (resolved by adjudicator)
  - Missing relations (one rater skipped): 2 cases

### Known Quality Issues

#### False Positives (in gold)

- **Count:** ~30 relations (~3.3% of gold)
- **Examples:** LLM-extracted relations that passed annotation but are marginal calls
- **Impact:** Slightly inflates precision of baselines; use confidence filtering to mitigate

#### False Negatives (in gold)

- **Count:** Estimated ~156 missing relations (~18% of true relations)
- **Root cause:** Annotators skipped dense articles; some relations are subtle
- **Impact:** Recall likely underestimated; Recall-ceiling ≈ 0.82
- **Audit:** See [QUALITY.md](QUALITY.md) for detailed gap analysis

#### Dirty Periods

##### 2015–2016: Campaign Financing Scandal + Constitutional Process

- **Articles:** 479 (from 234k total)
- **Annotated relations:** 198 (21.7% of gold)
- **Issues:**
  - Government (Bachelet admin) heavily criticized; noisier relations
  - Constitutional debate introduced new actors; entity linking harder
- **Recommendation:** Use with caution; consider separate eval set

##### 2019-H2: Social Outbreak

- **Articles:** 45 (dense, protest-focused)
- **Annotated relations:** 12
- **Issues:**
  - Street actors (protest organizers) vs institutional actors; sparse elite focus
- **Recommendation:** Exclude from benchmark eval; analyze separately

---

## Comparison to Other Datasets

### Spanish-language NLP Corpora

| Dataset | Size | Language | Signed? | Temporal? | License |
|---|---|---|---|---|---|
| **This dataset** | 2.1M articles | Spanish (Chilean) | Yes | Yes (25 years) | CC-BY-NC |
| COPA | 200k tweets | Spanish (mixed) | No | No | Academic |
| TASS (Wnut) | 7.2k tweets | Spanish (mixed) | Yes | No | CC-BY-NC |
| SentiRec | 360k news | Spanish (mixed) | No | No | Academic |

**Unique contribution:** Only large-scale, signed, temporally-stratified Spanish political dataset.

### Signed Graph Datasets

| Dataset | Nodes | Edges | Signed | Source |
|---|---|---|---|---|
| Wikipedia RfA | 10.8k | 159k | Yes | SNAP |
| Slashdot | 82k | 549k | Yes | SNAP |
| Bitcoin-OTC | 5.9k | 35k | Yes | SNAP |
| **This dataset (per snapshot)** | ~250 | ~1,500 | Yes | News extraction |

**Unique contribution:** Temporal dynamics (25 snapshots); realistic political context.

---

## Recommendations for Use

### ✅ Best For

- Longitudinal network analysis (temporal stability, realignment detection)
- Benchmarking signed graph algorithms (community detection, balance index)
- Spanish NLP research (relation extraction, entity linking on news)
- Political science validation (quantify elite polarization over time)

### ⚠️ Use with Caution

- Local politics (dataset focuses on national elite)
- Formal Spanish (excludes colloquial, informal speech)
- Post-2021 analysis (COVID period has lower coverage; 2024 is partial year)
- 2015–2016 period (see "Dirty Periods" above)

### ❌ Not Recommended For

- Real-time prediction (historical data only)
- Commercial applications (CC-BY-NC license)
- Single-outlet analysis (Emol/Tercera dominate; diversify if needed)
- Sub-national politics (insufficient coverage)

---

## How to Access

### S3 Download

```bash
# Raw CSV (all 2.1M articles)
aws s3 cp s3://chilean-political-dataset/articles_raw_v2.csv ./data/raw/

# Processed Parquet (cleaned, tokenized)
aws s3 cp s3://chilean-political-dataset/articles_v2.parquet ./data/processed/

# Gold standard & splits
aws s3 cp s3://chilean-political-dataset/gold_relations_v2.parquet ./data/gold/
aws s3 cp s3://chilean-political-dataset/splits.json ./data/gold/
```

### Or Use the Download Script

```bash
python scripts/download.py --what all  # all tiers
python scripts/download.py --what raw  # raw CSV only
python scripts/download.py --what processed  # processed Parquet only
python scripts/download.py --what gold  # gold + splits only
```

---

## Versioning

| Version | Release Date | Articles | Gold Relations | Major Changes |
|---|---|---|---|---|
| **2.0** | 2024-06 | 2,100,000 | 914 | Full dataset; 25 snapshots; realignment detection |
| **1.0** | 2024-03 | 93 | 150 | Pilot; thesis validation only |

---

## Cite This Dataset

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
