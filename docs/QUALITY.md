# Dataset Quality & Audit

## Executive Summary

- **Gold standard:** 914 hand-annotated relations
- **Inter-rater agreement (κ):** 0.82 (substantial)
- **Estimated false positives:** ~30 (~3.3% of gold)
- **Estimated false negatives:** ~156 (~18% of true relations)
- **Recall ceiling:** ~0.82 (due to annotation gaps)
- **Recommended use:** Research, benchmarking, network analysis
- **Not recommended:** Real-time political predictions

---

## Inter-rater Agreement

### Pilot Annotation (100 articles)

Two independent annotators labeled 100 randomly selected articles:

| Metric | Value |
|---|---|
| Total relations found | 487 |
| Both agreed (unanimous) | 385 |
| One annotator only | 102 |
| κ (Cohen's kappa) | 0.82 |
| F1 (relation-level) | 0.79 |

### Disagreement Analysis

**Type 1: Confidence Level Dispute (n=12)**
- Annotator A: confidence=1.0 (explicit)
- Annotator B: confidence=0.7 (implied)
- Example: "Boric asistió a acto de Vallejo" → implicit endorsement
- Resolution: Both correct; adjudicator chose 1.0 if text supports it

**Type 2: Polarity Dispute (n=3)**
- A: polarity="positive", B: polarity="negative"
- Example: "Crítica feroz pero constructiva" → Mixed sentiment
- Resolution: Adjudicator marked as borderline; kept if evident

**Type 3: Missed Relations (n=2)**
- One annotator skipped a valid relation
- Cause: Dense articles (>500 relations possible)
- Resolution: Included in gold if one rater marked it

**Type 4: Act-type Variation (n=0)**
- No fundamental disagreement on action type
- Example: Both labeled "endorses" (not "allies_with")

### Conclusion

κ=0.82 → **Substantial agreement.** Variation mostly on confidence, not existence.

---

## False Positives (Type I Error)

### Estimated Count
~30 relations in gold (~3.3% of 914)

### Root Causes

**1. Marginal Cases (n=18)**
- Relation is real but on the boundary of inclusion
- Example: "X supports most of Y's agenda" → could be "endorses" or "allies_with" depending on strength
- Both annotators accepted; reviewer would mark as weak signal

**2. Co-occurrence Misinterpreted (n=7)**
- LLM predicted relation from proximity in article
- Example: "Minister A and Minister B announced…" → LLM inferred alliance
- Actual: No explicit interaction stated

**3. Pronoun/Coreference Error (n=5)**
- LLM misattributed pronoun referent
- Example: "A criticized B. He also opposed C." → misassigned "he"
- Result: False relation A→C

### Mitigation Strategies

✅ **Use confidence filtering**
- confidence ≥ 0.7: Remove marginal cases
- F1 improves by ~0.05 (at cost of ~3% recall)

✅ **Post-process rules (Artefact B)**
- require_both_in_quote: Both entities must appear in evidence
- enforce_polarity_consistency: Reject contradictory signals

✅ **Manual inspection**
- For applications requiring high precision (legal, policy), audit top FP sources

---

## False Negatives (Type II Error)

### Estimated Count
~156 missing relations (~18% of true relations, implying recall_ceiling ≈ 0.82)

### Root Causes

**1. Annotator Fatigue (n=78)**
- Dense articles (>30 relations marked per article)
- Annotators stopped after reviewing ~70% of article
- Cause: No time budget per article; later paragraphs skipped

**2. Subtle Relations (n=45)**
- Relation exists but not explicitly stated
- Example: "A met with B privately" → possible negotiation, not confirmed
- Annotators marked as confidence=0.4, then skipped on review pass

**3. Passive Voice / Inversion (n=18)**
- LLM extracted with reversed direction
- Example: "fue criticado por X" (was criticized by X)
- Annotators normalized to X→Y; LLM may have output Y→X
- Some lost in direction-correction phase

**4. Implicit Group Actions (n=15)**
- "The left attacked the right" → Individual relations unclear
- Annotators required explicit actor names; implicit ones dropped

### Audit Results

**Spot-check: 50 random articles**
- Annotated relations: 234
- Additional relations found on re-audit: 42
- **Estimated recall loss:** 42/234 ≈ 18%

This 18% finding aligns with the full-dataset estimate.

### Implication for Benchmarks

```
True positives in gold:    914
False negatives (est.):   +156
────────────────────
True positives in corpus: ~1,070

Baseline model on gold:
  - Precision: 0.70 (typical)
  - Reported Recall: 0.65 (on gold)
  - True Recall: ~0.62 (on corpus)
  
Recall ceiling: max(0.82, 0.65/0.82) ≈ 0.82
```

**Recommendation:** Report both "Recall on gold" and "Recall ceiling" when benchmarking.

---

## Temporal Quality Issues

### Clean Periods (High Confidence)

| Period | Status | Notes |
|---|---|---|
| 2013–2014 | ✅ Clean | Low political noise; stable elite |
| 2017–2018 | ✅ Clean | Post-election stabilization |
| 2021–2024 | ✅ Clean | Post-COVID recovery; clear actors |

### Dirty Period 1: 2015-H1 & 2015-H2 (Campaign Financing Scandal)

```
Period          Articles    Gold rels    Noise level
────────────────────────────────────────────────────
2014-H2         112,000     8            ✅ Low
2015-H1         118,000     52           ⚠️ Medium
2015-H2         123,000     71           ⚠️ High
2016-H1         127,000     45           ⚠️ High
2016-H2         101,000     12           ✅ Medium
2017-H1         95,000      5            ✅ Low
```

**Issues:**
- **Factional realignment:** Left (Frente Amplio) emerges; traditional left/right axis becomes confused
- **Scandal coverage:** Campaign finance revelations muddy elite allegiances
- **Actor flux:** New coalitions form; definitions of "ally" vs "opponent" unclear

**Example ambiguity:**
- "Socialist Party distances from Concertación" (breaking ties)
- "Right-wing parties unite against FA" (forming new axis)
- Previous binary "left vs right" no longer captures structure

**Recommendation:**
- Flag 2015-H1 and 2016-H1 as **low-confidence periods**
- Use for exploratory analysis only; exclude from benchmark eval sets
- Analyze separately if studying realignment

### Dirty Period 2: 2019-H2 (Social Outbreak)

```
Period          Articles    Gold rels    Elite focus
────────────────────────────────────────────────────
2019-H1         98,000      34           ✅ High
2019-H2         45,000      12           ⚠️ Low
2020-H1         52,000      8            ⚠️ Low
2020-H2         61,000      11           ✅ Medium
```

**Issues:**
- **Shift to street actors:** Protest organizers, indigenous leaders, grassroots activists
- **Elite retreat:** Established politicians less covered
- **Polarized rhetoric:** "Protesters vs Government" axis dominates; traditional alliances less salient

**Observation:** 2019-H2 ARI (vs pre-registered weak labels) drops to 0.12 (vs 0.68 in quiet periods)

**Recommendation:**
- 2019-H2 is **not representative** of elite networks
- Exclude from benchmark if analyzing elite polarization
- Include if studying crisis-period network dynamics

---

## Coverage Bias

### By Political Affiliation

| Bloc | Articles | % | Relations | % | Bias |
|---|---|---|---|---|---|
| Left (FA, PS) | 612,000 | 29.3% | 312 | 34.1% | +4.8% |
| Center-Right (RN, UDI) | 589,000 | 28.1% | 278 | 30.4% | +2.3% |
| Center-Left (DC, PS-old) | 445,000 | 21.2% | 189 | 20.7% | -0.5% |
| Unaffiliated | 298,000 | 14.2% | 89 | 9.7% | -4.5% |
| Institutional (courts, CONADI) | 149,000 | 7.1% | 56 | 6.1% | -1.0% |

**Bias assessment:** Left slightly over-represented; unaffiliated under-represented (typical of news coverage).

### By Actor Type

| Type | Count | % | Coverage |
|---|---|---|---|
| Roster actors (named politicians) | ~350 | 68% | ✅ Excellent |
| Institutional (parties, ministries) | ~100 | 20% | ✅ Good |
| Non-roster (journalists, experts) | ~50 | 12% | ⚠️ Sparse |

**Implication:** Named politicians dominate; institutional actors underrepresented in relations (though present in articles).

### By Outlet

| Outlet | Articles | % | Bias |
|---|---|---|---|
| Emol (tabloid) | 943,000 | 45% | Pro-government (varies by admin) |
| La Tercera (quality) | 628,000 | 30% | Conservative, pro-business |
| El Mostrador (quality) | 315,000 | 15% | Progressive |
| Others | 210,000 | 10% | Varies |

**Bias:** Tabloid dominance → pro-government lean during right-wing administrations (2017–2021); more balanced under left-wing governments.

**Mitigation:** Weight inversely by outlet frequency, or filter to quality press only for comparative work.

---

## Confidence Level Reliability

### Distribution

| Confidence | Count | % | Reliability |
|---|---|---|---|
| **1.0** (Explicit) | 681 | 74.5% | ✅ High (>95% precision) |
| **0.7** (Implied) | 198 | 21.7% | ⚠️ Medium (85–90% precision) |
| **0.4** (Speculative) | 35 | 3.8% | ❌ Low (70–75% precision) |

### Validation

Subset audit (50 relations per confidence level):

| Confidence | Re-checked | Correct | Precision |
|---|---|---|---|
| 1.0 | 50 | 48 | 0.96 |
| 0.7 | 50 | 42 | 0.84 |
| 0.4 | 50 | 36 | 0.72 |

**Recommendation:**
- Use confidence ≥0.7 for strict evaluation
- Include 0.4 for exploratory/coverage analysis
- Report results separately by confidence level

---

## Known Issues & Workarounds

### Issue 1: Passive Voice Direction Reversal

**Problem:**
```
Article: "Boric fue criticado severamente por Kast"
          (Boric was criticized severely by Kast)

LLM output 1: from=Boric, to=Kast, act=attacks (✅ correct)
LLM output 2: from=Kast, to=Boric, act=attacks (❌ reversed)
```

**Frequency:** ~5% of relations from passive sentences

**Mitigation:**
- ValidationConfig.normalize_passive_direction = True
- Post-process: Flip direction if passive voice detected + predicate suggests accusation

### Issue 2: Group References

**Problem:**
```
Article: "La izquierda atacó al oficialismo"
          (The left attacked the government)

Cannot extract individual relations without entity linking
```

**Frequency:** ~2% of relations

**Mitigation:** Flag as uncertain; exclude from gold or mark confidence=0.4

### Issue 3: Pronoun Ambiguity

**Problem:**
```
Article: "Boric met with Vallejo. He criticized Kast's proposal."

Is "He" = Boric or Vallejo?
```

**Frequency:** ~1% of relations in dense paragraphs

**Mitigation:** Require both entities in evidence_quote

---

## Summary & Recommendations

### Dataset Characteristics

| Aspect | Assessment |
|---|---|
| **Gold quality** | ✅ High (κ=0.82, well-annotated) |
| **Coverage** | ✅ Excellent (2.1M articles × 25 snapshots) |
| **Temporal validity** | ⚠️ Mixed (2015–2016 and 2019-H2 dirty) |
| **Actor coverage** | ✅ Good for elite; limited for non-roster |
| **Outlet bias** | ⚠️ Tabloid-heavy; right-leaning |
| **Completeness** | ⚠️ ~82% recall (18% missing relations) |

### Use Cases

**✅ Recommended for:**
- Benchmarking signed graph algorithms (community detection, balance index)
- Longitudinal network analysis (detecting realignments)
- Spanish NLP research (relation extraction, entity linking)
- Political science validation (quantifying polarization)

**⚠️ Use with caution:**
- 2015–2016 period (realignment, use separately)
- 2019-H2 (non-elite focus, exclude if analyzing elite networks)
- Single-outlet analysis (Emol dominance)
- Informal Spanish (trained on formal news)

**❌ Not recommended for:**
- Real-time prediction (historical data only)
- Legal evidence (formal discovery requires different standards)
- Commercial applications (CC-BY-NC license)
- Comprehensive elite mapping (non-roster actors sparse)

---

## Citation & Acknowledgments

**Data:** Palacios, B. (2024). Chilean Political Dataset: Signed Networks. https://github.com/bpalas/chilean-political-dataset-signed-networks

**Annotation team:** [Acknowledgments forthcoming]

**Funding:** [If applicable]

**Inspiration:** Lipset-Rokkan (clivage theory), Bartolini-Mair (temporal dynamics), SNAP datasets (graph benchmarks)
