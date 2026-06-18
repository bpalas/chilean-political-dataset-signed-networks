# Project Status & Next Steps

## Current State (2024-06-18)

### ✅ Completed
- Dataset backbone structure
- README (high-level overview + quick start)
- SCHEMA.md (comprehensive field definitions)
- DATASET.md (statistics, coverage analysis, quality metrics)
- Scripts (download.py, stats.py)
- Tests (schema validation)
- Packaging (pyproject.toml, requirements.txt)
- Citation info (CITATION.cff)
- License (CC-BY-NC-4.0)

### 🔄 In Progress
- Data upload to S3 (TODO: configure bucket, checksums)
- Zenodo integration (TODO: create Zenodo record, get DOI)
- Full test suite (TODO: add integrity tests, reproducibility checks)

### ❌ To Do
1. **Docs (2 weeks)**
   - DATA_COLLECTION.md (preprocessing pipeline, reproducibility)
   - QUALITY.md (detailed quality analysis, gap audit)
   - CONTRIBUTING.md (how to add annotations, report issues)

2. **Paper (4-6 weeks)**
   - Main paper (8-10 pages) describing dataset construction, quality, applications
   - Target venues: LREC, ACL Findings, ICWSM
   - Proof of concept: reproducible analysis using clivaje-framework

3. **Integration (2 weeks)**
   - Link from README to related repos (text2sg, clivaje-framework)
   - Add download script tests (verify checksums match S3)
   - Add example notebook (load dataset + quick analysis)

4. **Publication (1 week)**
   - Push to GitHub public
   - Upload to Zenodo (get DOI)
   - Register CITATION.cff
   - Announce on Twitter/academic channels

---

## Parallel Work

While docs/paper are in progress:

- **clivaje-etl** (Rust): Read + preprocess 2.1M articles
- **text2sg-dist** (Go): Orchestrate LLM calls to Ollama
- **clivaje-framework**: Production 5-stage analysis

Timeline: Months 2-3 of project → all repos converge to single narrative for publication.

---

## Success Metrics

### By Sept 2024
- Dataset paper accepted/submitted
- 6 GitHub repos publicly linked (text2sg, clivaje-networks, clivaje-dataset, clivaje-framework, clivaje-etl, text2sg-dist)
- Zenodo DOI active
- >100 GitHub stars (combined repos)

### By Dec 2024
- Paper published (LREC/ACL/ICWSM)
- First external researchers cite the dataset
- CV update complete for PhD/postdoc applications

---

## Notes for Collaborators

- **Data sensitivity:** No personal data, but articles are copyrighted. CC-BY-NC balances openness + protection.
- **Versioning:** v2.0 is stable; v3.0 planned for end-2024 with expanded outlets + updated actors.
- **Reproducibility:** All preprocessing scripted (Rust ETL); anyone can regenerate from raw CSVs.

---

## Questions

- [ ] S3 bucket configured? (for download.py to work)
- [ ] Zenodo account set up?
- [ ] GitHub public repo URL confirmed?
- [ ] Any external contributors/co-authors?
