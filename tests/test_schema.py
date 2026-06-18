"""Test dataset schema compliance."""
from __future__ import annotations

import pytest


VALID_ACT_TYPES = {
    "endorses", "attacks", "allies_with", "calls_on", "distances_from",
    "questions", "negotiates_with", "competes_with", "accuses",
}

VALID_POLARITIES = {"positive", "negative", "neutral"}


def test_act_types():
    """Verify all 9 act_types are defined."""
    assert len(VALID_ACT_TYPES) == 9
    assert "endorses" in VALID_ACT_TYPES
    assert "attacks" in VALID_ACT_TYPES


def test_polarity():
    """Verify polarity values."""
    assert len(VALID_POLARITIES) == 3
    assert "positive" in VALID_POLARITIES
    assert "negative" in VALID_POLARITIES
    assert "neutral" in VALID_POLARITIES


def test_relation_example():
    """Test a valid relation dict."""
    relation = {
        "article_id": "emol_20150623_001",
        "from_entity": "Gabriel Boric",
        "to_entity": "Camila Vallejo",
        "act_type": "endorses",
        "polarity": "positive",
        "issue": "presidential_election",
        "evidence_quote": "Boric respaldó las propuestas de Vallejo",
        "confidence": 1.0,
        "period": "2015-H1",
    }

    # Validate
    assert relation["act_type"] in VALID_ACT_TYPES
    assert relation["polarity"] in VALID_POLARITIES
    assert 0.0 <= relation["confidence"] <= 1.0
    assert relation["from_entity"] != relation["to_entity"]
    assert len(relation["evidence_quote"]) >= 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
