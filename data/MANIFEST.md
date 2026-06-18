# Data Directory Manifest

## Structure

```
data/
├── raw/              (2.1M articles, raw CSV, ~1.2 GB)
├── processed/        (2.1M articles, Parquet, ~500 MB)
├── gold/             (914 relations + splits, ~10 MB)
└── MANIFEST.md       (this file)
```

---

## raw/

**Purpose:** Original news articles as exported from source outlets.

**Files:**
- `articles_raw_v2.csv.gz` (2.1M rows, gzipped)

**Columns:**
```
article_id,outlet,date,headline,body,url,author
```

**Size:** ~1.2 GB (compressed)

**Access:** Download with:
```bash
python scripts/download.py --what raw
```

**License:** CC-BY-NC-4.0 (articles from public news outlets, aggregated with attribution)

---

## processed/

**Purpose:** Cleaned and tokenized articles in Parquet format (efficient for analysis).

**Files:**
- `articles_v2.parquet`

**Columns:**
```
article_id (str)
outlet (str)
date (str, ISO 8601)
period (str, e.g., "2015-H1")
headline (str)
body (str, cleaned)
body_tokens (int)
url (str)
author (str, may be null)
topics (list[str], BERT topic labels if available)
```

**Size:** ~500 MB

**Access:** Download with:
```bash
python scripts/download.py --what processed
```

**Example usage:**
```python
import pandas as pd
articles = pd.read_parquet("data/processed/articles_v2.parquet")
print(f"Loaded {len(articles)} articles")
print(articles[["article_id", "period", "body_tokens"]].head())
```

---

## gold/

**Purpose:** Hand-annotated relations and official train/val/test splits.

**Files:**

### gold_relations_v2.parquet
914 hand-annotated relations (high-quality ground truth).

**Columns:**
```
article_id (str)
from_entity (str)
to_entity (str)
act_type (str, one of 9 types)
polarity (str, {positive, negative, neutral})
issue (str, domain)
evidence_quote (str, substring from article)
confidence (float, {1.0, 0.7, 0.4})
period (str, e.g., "2015-H1")
```

**Example usage:**
```python
import pandas as pd
gold = pd.read_parquet("data/gold/gold_relations_v2.parquet")
print(f"{len(gold)} relations in gold standard")
# Filter by confidence
explicit = gold[gold['confidence'] == 1.0]
print(f"{len(explicit)} explicit relations")
```

### splits.json
Train/val/test split (stratified by period and outlet).

**Format:**
```json
{
    "train": ["article_id_001", "article_id_002", ...],  # 60%
    "val": ["article_id_250", ...],                       # 20%
    "test": ["article_id_500", ...]                       # 20%
}
```

**Example usage:**
```python
import json
with open("data/gold/splits.json") as f:
    splits = json.load(f)
print(f"Train: {len(splits['train'])}, Val: {len(splits['val'])}, Test: {len(splits['test'])}")

# Load train set
train_articles = articles[articles['article_id'].isin(splits['train'])]
train_relations = gold[gold['article_id'].isin(splits['train'])]
```

**Size:** ~10 MB (combined)

**Access:** Download with:
```bash
python scripts/download.py --what gold
```

---

## Getting Started

### 1. Download All Data
```bash
python scripts/download.py --what all
```

### 2. Load and Explore
```python
import pandas as pd
import json

# Articles
articles = pd.read_parquet("data/processed/articles_v2.parquet")
print(f"Total: {len(articles)} articles")

# Relations
gold = pd.read_parquet("data/gold/gold_relations_v2.parquet")
print(f"Gold standard: {len(gold)} relations")

# Splits
with open("data/gold/splits.json") as f:
    splits = json.load(f)

# Train set
train_rels = gold[gold['article_id'].isin(splits['train'])]
print(f"Train: {len(train_rels)} relations")
```

### 3. Print Statistics
```bash
python scripts/stats.py
```

---

## Notes

- **Storage:** Total ~1.7 GB (if you download raw + processed + gold)
  - Recommended: processed + gold (~510 MB)
  - Minimal: gold only (~10 MB)

- **Versioning:** All files are v2 (v1 was pilot, deprecated)

- **Raw data:** Kept for reproducibility; rarely needed for analysis

- **Updates:** v3.0 planned for 2024-Q4 with expanded outlets and updated actor lists

---

## Questions

- Storage space limited? Download `gold/` only; then request `processed/` on demand
- Need raw CSV? Use `raw/articles_raw_v2.csv.gz`; decompress with `gunzip`
- Custom split? Modify `splits.json` locally; scripts will respect it
