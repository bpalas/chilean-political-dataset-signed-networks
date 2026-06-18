#!/usr/bin/env python
"""Print dataset statistics."""
from __future__ import annotations

from pathlib import Path
import json


def print_stats() -> None:
    """Print dataset statistics from DATASET.md and splits."""
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"

    print("\n" + "=" * 70)
    print("CHILEAN POLITICAL DATASET — Statistics")
    print("=" * 70)

    # Dataset size
    print("\nDATASET SIZE:")
    print("  Total articles:    2,100,000+")
    print("  Time period:       2013-01-01 to 2024-06-30 (11.5 years)")
    print("  Snapshots:         23 semesters")
    print("  Gold relations:    914 (hand-annotated)")
    print("  Weak labels:       ~18% coverage")

    # Actors
    print("\nACTORS:")
    print("  Roster (politicians):      ~350")
    print("  Institutional (parties):   ~100")
    print("  Non-roster (journalists):  ~50+")
    print("  Total unique:              ~500")

    # Outlets
    print("\nNEWS OUTLETS:")
    outlets = {"Emol": "45%", "La Tercera": "30%", "El Mostrador": "15%", "Others": "10%"}
    for outlet, pct in outlets.items():
        print(f"  {outlet:<20} {pct:>8}")

    # Relations by type
    print("\nRELATIONS BY TYPE (gold standard, n=914):")
    relations = {
        "attacks": (289, "31.6%"),
        "endorses": (245, "26.8%"),
        "calls_on": (102, "11.2%"),
        "questions": (89, "9.7%"),
        "allies_with": (78, "8.5%"),
        "distances_from": (45, "4.9%"),
        "negotiates_with": (34, "3.7%"),
        "competes_with": (21, "2.3%"),
        "accuses": (11, "1.2%"),
    }
    for act_type, (count, pct) in relations.items():
        print(f"  {act_type:<20} {count:>3}  ({pct})")

    # Polarity
    print("\nPOLARITY (gold standard, n=914):")
    polarity = {"negative (−)": (544, "59.5%"), "positive (+)": (287, "31.4%"), "neutral (~)": (83, "9.1%")}
    for pol, (count, pct) in polarity.items():
        print(f"  {pol:<20} {count:>3}  ({pct})")

    # Confidence
    print("\nCONFIDENCE LEVELS (gold standard, n=914):")
    confidence = {"1.0 (explicit)": (681, "74.5%"), "0.7 (implied)": (198, "21.7%"), "0.4 (speculative)": (35, "3.8%")}
    for conf, (count, pct) in confidence.items():
        print(f"  {conf:<25} {count:>3}  ({pct})")

    # Splits
    splits_path = data_dir / "gold" / "splits.json"
    if splits_path.exists():
        print("\nTRAIN/VAL/TEST SPLIT:")
        with open(splits_path) as f:
            splits = json.load(f)
        total = sum(len(v) for v in splits.values())
        for split_name, articles in splits.items():
            pct = 100 * len(articles) / total if total > 0 else 0
            print(f"  {split_name:<10} {len(articles):>6}  ({pct:>5.1f}%)")
    else:
        print("\nTRAIN/VAL/TEST SPLIT:")
        print("  (splits.json not found — download with: python scripts/download.py)")

    # Issues
    print("\nKNOWN QUALITY ISSUES:")
    print("  False positives (in gold):  ~30 relations (~3.3%)")
    print("  False negatives (estimated): ~156 missing (~18%)")
    print("  Dirty period 2015-H1/2016-H1: High noise, use with caution")
    print("  2019-H2 (social outbreak):    Sparse elite focus")
    print("  Coverage bias:                Pro-formal speech, pro-elite")

    print("\n" + "=" * 70)
    print("For more details, see: docs/DATASET.md and docs/QUALITY.md")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    print_stats()
