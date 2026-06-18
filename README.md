# Chilean Political Dataset: Signed Networks

[![License: CC-BY-NC-4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
![Version](https://img.shields.io/badge/version-2.0-blue)
![Status](https://img.shields.io/badge/status-active-brightgreen)

**2.1M Spanish-language news articles (2013–2024) with 914 hand-annotated political relations, enabling longitudinal analysis of Chilean elite networks over 25 semi-annual snapshots.**

---

## Overview

This dataset captures political relations in Chile across 11 years by extracting signed graphs (endorses, attacks, allies_with, …) from news coverage. It enables research into:

- **Temporal polarization dynamics** — How does elite alignment/opposition evolve?
- **Structural realignment** — When do coalitions break? (detected: 2015–2016)
- **Community detection at scale** — Benchmark for signed graph partitioning
- **Multilingual NLP** — Spanish-language extraction, applicable to other countries

### Key Statistics

| Metric | Value |
|---|---|
| **Time period** | 2013–2024 (11 years, 22 semesters) |
| **Total articles** | 2,100,000+ |
| **Unique political actors** | ~500 (politicians, parties, ministers) |
| **Gold standard relations** | 914 (hand-annotated, high quality) |
| **Relation types** | 9 (endorses, attacks, allies_with, calls_on, distances_from, questions, negotiates_with, competes_with, accuses) |
| **Languages** | Spanish (Chilean news outlets) |
| **Format** | Parquet (processed), CSV (raw) |

---

## Quick Start

### Installation

```bash
git clone https://github.com/bpalas/chilean-political-dataset-signed-networks
cd chilean-political-dataset-signed-networks
pip install -r requirements.txt
```

### Download & Validate

```bash
# Download processed dataset (Parquet)
python scripts/download.py

# Validate integrity (checksums, schema)
python scripts/validate.py

# Print dataset statistics
python scripts/stats.py
```

### Load in Python

```python
import pandas as pd

# Load articles
articles = pd.read_parquet("data/processed/articles_v2.parquet")
print(f"Loaded {len(articles)} articles")

# Load gold standard relations
gold = pd.read_parquet("data/gold/gold_relations_v2.parquet")
print(f"{len(gold)} annotated relations")

# Load train/val/test split
import json
splits = json.load(open("data/gold/splits.json"))
print(f"Train: {len(splits['train'])}, Val: {len(splits['val'])}, Test: {len(splits['test'])}")
```

---

## Dataset Composition

### Data Tiers

| Tier | Size | Format | License | Access |
|---|---|---|---|---|
| **Raw articles** | 2.1M | CSV | CC-BY-NC-4.0 | Public (S3) |
| **Processed (v2)** | ~500MB | Parquet | CC-BY-NC-4.0 | Public (S3) |
| **Gold relations** | 914 | Parquet | CC-BY-NC-4.0 | Public (repo) |
| **Weak labels** | ~18% coverage | JSON | CC-BY-NC-4.0 | Public (repo) |

### Temporal Coverage

```
2013-H1 ──┬── 2013-H2 ──┬── ... ──┬── 2024-H1
          │             │         │
      Semester 1     Semester 2   Semester 22 (latest)

Each snapshot: nNodes ≈ 100–250, nEdges ≈ 500–2000
```

---

## Documentation

| Document | Purpose |
|---|---|
| **[DATASET.md](docs/DATASET.md)** | Comprehensive statistics, sources, coverage analysis |
| **[SCHEMA.md](docs/SCHEMA.md)** | Relation format, field descriptions, examples |
| **[DATA_COLLECTION.md](docs/DATA_COLLECTION.md)** | How it was built, preprocessing pipeline, reproducibility |
| **[QUALITY.md](docs/QUALITY.md)** | Inter-rater agreement, known gaps, limitations, audit findings |
| **[PAPER.md](docs/PAPER.md)** | Full academic paper (dataset contribution) |

---

## Benchmark: Baseline Results

Evaluated on the gold standard (914 relations) using three extraction frameworks:

| System | Precision | Recall | F0.5 |
|---|---|---|---|
| BERT baseline | 0.65 | 0.58 | 0.63 |
| text2sg (SOTA) | 0.928 | 0.901 | 0.922 |
| Human agreement (κ) | 0.82 | — | — |

→ **Provides a realistic difficulty level**: not too easy (baseline at 0.63), not impossible (humans at κ=0.82).

---

## Citation

If you use this dataset, please cite:

```bibtex
@dataset{palacios2024chilean,
  author  = {Palacios, Benjamin},
  title   = {Chilean Political Dataset: Signed Networks (2013–2024)},
  year    = {2024},
  version = {2.0},
  url     = {https://github.com/bpalas/chilean-political-dataset-signed-networks},
  doi     = {10.5281/zenodo.XXXXXXX}  # filled after Zenodo upload
}
```

See [CITATION.cff](CITATION.cff) for other formats (BibTeX, RIS, APA).

---

## License & Reuse

- **Code** (Python, Rust, Go): [MIT](LICENSE)
- **Dataset & annotations**: [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/)
  - ✅ Use for research, education
  - ✅ Cite the dataset
  - ❌ Commercial redistribution without permission

**Raw news articles:** Sourced from publicly available outlets (La Tercera, El Mostrador, Emol, …). Dataset aggregates with attribution preserved.

---

## Related Work

This dataset enables benchmarking of:

- **text2sg** ([github.com/bpalas/text2SG](https://github.com/bpalas/text2SG)) — Signed graph extraction from text
- **clivaje-framework** ([github.com/bpalas/clivaje-framework](https://github.com/bpalas/clivaje-framework)) — Longitudinal network analysis (5-stage pipeline, realignment detection)
- **clivaje-etl** ([github.com/bpalas/clivaje-etl](https://github.com/bpalas/clivaje-etl)) — Fast preprocessing of 2.1M articles (Rust)

---

## Versioning

| Version | Release | Changes |
|---|---|---|
| **2.0** | 2024-06 | Full dataset: 2.1M articles, 914 gold relations, 25 snapshots |
| **1.0** | 2024-03 | Pilot: 93 articles, 150 relations (thesis validation) |

We follow [semantic versioning](https://semver.org/). Minor versions add articles/snapshots; major versions refactor schema or methodology.

---

## Contributing

We welcome:
- 🐛 Bug reports (validation errors, schema issues)
- 📝 Annotations (if you want to expand gold standard)
- 🔍 Audits (quality checks, coverage gaps)

See [CONTRIBUTING.md](CONTRIBUTING.md) (forthcoming).

---

## Contact & Support

- **Issues**: [GitHub Issues](https://github.com/bpalas/chilean-political-dataset-signed-networks/issues)
- **Email**: [benja.pala01@gmail.com](mailto:benja.pala01@gmail.com)
- **Citation questions**: See [CITATION.cff](CITATION.cff)

---

## Acknowledgments

- **Annotation team**: [names/institutions]
- **Data sources**: La Tercera, El Mostrador, Emol, [others]
- **Funding**: [if applicable]
- **Inspiration**: Lipset-Rokkan (clivage theory), Bartolini-Mair (temporal dynamics), SNAP datasets (graph benchmarks)
