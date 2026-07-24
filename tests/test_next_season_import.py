from __future__ import annotations

import ausl_data


def test_media_guide_context_follows_latest_season(monkeypatch):
    monkeypatch.setattr(ausl_data, "SEASONS", {2025: 270, 2026: 369, 2027: 400})

    context = ausl_data.media_guide_source_context()

    assert context["guide_year"] == 2027
    assert context["source_name"] == "2027 AUSL Media Guide"
    assert context["source_url"].endswith("2027-AUSL-Media-Guide.pdf")
    assert context["note_category_keys"]["current_outlook"] == "2027_outlook"
    assert context["note_category_keys"]["current_context"] == "2027_context"
    assert context["note_category_keys"]["previous_recap"] == "2026_recap"
