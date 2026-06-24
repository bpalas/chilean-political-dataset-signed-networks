# Chilean Political Signed Networks (2014–2026)

[![HF Dataset: Signed Network](https://img.shields.io/badge/🤗%20Dataset-Signed%20Network-yellow)](https://huggingface.co/datasets/bpalacios/chilean-political-signed-network)
[![HF Dataset: Gold](https://img.shields.io/badge/🤗%20Dataset-Gold%20Benchmark-yellow)](https://huggingface.co/datasets/bpalacios/text2signed-graph-gold)
[![HF Collection](https://img.shields.io/badge/🤗%20Collection-text2SG-blue)](https://huggingface.co/collections/bpalacios/chilean-political-signed-networks-6a3c4ed962e91cb05cf4855a)
![Status](https://img.shields.io/badge/status-active-brightgreen)

**A signed directed network of Chilean political actors (2014–2026), extracted at scale from
~480k news articles spanning three governments. Each edge is a polarized political act —
`actor_u → act_type → actor_v` with a sign (+1 ally / −1 antagonist / 0 neutral).**

`480,002 articles · 442k actor nodes · 2.54M signed edges · 3 governments · 92% structural balance`

---

## Resources

| | Where | Notes |
|---|---|---|
| 🤗 **Signed network** (public) | [`chilean-political-signed-network`](https://huggingface.co/datasets/bpalacios/chilean-political-signed-network) | the graph: nodes + signed edges + metadata. **No article text** (copyright-safe). |
| 🤗 **Gold benchmark** (public) | [`text2signed-graph-gold`](https://huggingface.co/datasets/bpalacios/text2signed-graph-gold) | 287 synthetic articles · 914 gold signed relations. |
| 🤗 **Collection** | [text2SG](https://huggingface.co/collections/bpalacios/chilean-political-signed-networks-6a3c4ed962e91cb05cf4855a) | both datasets grouped. |
| ⚙️ **Extractor engine** | [`text2graph-evolve`](https://github.com/bpalas/text2graph-evolve) | evolutionary optimization of the extraction prompts. |

> The news corpus is copyrighted (CC-BY-NC). The public dataset ships only the **extracted
> graph + `article_id`** (= `md5(body)`), so corpus holders can join back — no article text.

---

## What it captures

A longitudinal map of who-relates-to-whom in Chilean politics across **three administrations**
(Bachelet II → Piñera II → Boric) and **two constitutional processes** (2020, 2023). Enables:

- **Polarization dynamics** — how elite alignment/antagonism evolves over 12 years.
- **Coalition structure & realignment** — Nueva Mayoría → Apruebo Dignidad; the right's split
  into Chile Vamos vs the republican right (Kast/Kaiser).
- **Signed-graph analysis** — community detection and structural balance at scale.

### Key statistics

| Metric | Value |
|---|---|
| Window | 2014–2026 (3 governments) |
| Articles (proportional sample of ~1M political) | 480,002 |
| Actor nodes (connected) | 239,684 |
| Signed edges | 2,539,835 |
| Polarity | 42% negative · 30% positive · 28% neutral |
| Node types | person · party · institution · coalition · movement · org |

---

## How it was built — the text2SG pipeline

Three passes, **precision-first** (a false edge pollutes the graph; a missed one only omits):

1. **NER** — `GLiNER` (zero-shot, local, fp16) tags typed political mentions. $0, deterministic.
2. **Entity resolution** — token-blocked fuzzy clustering (cross-type + surname guards),
   then curated: a deterministic layer (exact name + acronym dictionary `UDI ↔ Unión Demócrata
   Independiente`) followed by a **fan-out of 6 parallel LLM judges** (Sonnet) that resolve the
   semantic grey zone (`Ejecutivo`/`La Moneda` → `Gobierno de Chile`) — never merging distinct
   people, never crossing types.
3. **Relation extraction** — a tuned `gemini-2.5-flash-lite` extractor, given the resolved
   actors and abstaining without evidence, emits `(actor_u → act_type → actor_v, polarity)`.
   **f0.5 ≈ 0.92** against the gold benchmark. The edge **sign is the extracted polarity**.

## How it was validated — community detection + structural balance

Validated on **aggregate structure**, not edge-by-edge:

- **Community detection** (Louvain on the ally subgraph) reproduces the real coalitions and
  their evolution across 12 years, including the right's fragmentation; foreign actors cluster
  by ideology (Lula/Evo/Maduro with the left; Trump/Bolsonaro/Milei with the republican right).
- **Structural balance** — **92% of negative edge weight falls between communities** (enemies
  separated), consistent with balance theory → the signed structure is reliable.

> ⚠️ **Temporal role nodes** (`Gobierno de Chile`, `Oposición`, `Presidente`) change referent
> at each change of government — analyze their dyads **per period**, not aggregated.

---

## Quick start

```python
import duckdb
con = duckdb.connect()
# top antagonists, straight from the public dataset on HF (needs httpf + token-free for public)
con.execute("SET hf_token=''")
print(con.execute("""
  SELECT canonical, degree, pos_degree, neg_degree
  FROM 'hf://datasets/bpalacios/chilean-political-signed-network/nodes.parquet'
  ORDER BY degree DESC LIMIT 10""").df())
```

## Lineage

**gold benchmark → evolve the extractor → apply at scale**

1. [`text2signed-graph-gold`](https://huggingface.co/datasets/bpalacios/text2signed-graph-gold) — the synthetic gold standard.
2. [`text2graph-evolve`](https://github.com/bpalas/text2graph-evolve) — evolves the champion extractor against the gold (precision-first, f0.5 fitness).
3. **this repo** — runs the champion on 480k real articles → the signed network.

---

## License & citation

- **Code**: MIT · **Public graph dataset**: CC-BY-4.0 (no news text) · **Source corpus**: CC-BY-NC-4.0.

```bibtex
@misc{palacios_chilean_signed_networks,
  author = {Palacios, Benjamín},
  title  = {Chilean Political Signed Networks (2014–2026)},
  year   = {2026},
  url    = {https://github.com/bpalas/chilean-political-dataset-signed-networks}
}
```

**Contact:** Benjamín Palacios · [benja.pala01@gmail.com](mailto:benja.pala01@gmail.com)
