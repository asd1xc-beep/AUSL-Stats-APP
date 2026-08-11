from __future__ import annotations

import json

from phase7c_fixtures import manifest_dict, staging_dict
from ausl_college_import import build_envelope_from_staging, load_pilot_manifest, load_staging, render_review_packet


def packet():
    manifest = load_pilot_manifest(json.dumps(manifest_dict()).encode())
    staging = load_staging(json.dumps(staging_dict()).encode())
    envelope = build_envelope_from_staging(manifest, staging)
    return render_review_packet(manifest, envelope)


def test_report_is_deterministic_traceable_and_never_calls_candidates_air_ready():
    first = packet()
    assert first == packet()
    assert "Candidate facts for later review" in first
    assert "Source references" in first
    assert "air-ready" not in first.casefold()
    assert "source-0" in first and "candidate-7000" in first


def test_report_explains_completeness_missing_fields_and_aggregate_coverage():
    text = packet()
    assert "Aggregate coverage summary" in text
    assert "Players: 10" in text
    assert "Needs Review" in text
    assert "sections.achievements" in text
    assert "Unresolved identities:" in text
    assert "Recommended résumé section order" in text
