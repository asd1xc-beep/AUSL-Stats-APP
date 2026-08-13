from __future__ import annotations

import hashlib
from pathlib import Path

from ausl_college import CompletenessState, assess_completeness
from ausl_college_batch_approval import (
    load_aggregate_approval,
    validate_batch_approval,
)


ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT / "data" / "college_approved_batches" / "phase7e"
AGGREGATE = ROOT / "data" / "college_approved_phase7e"


def test_checked_in_batch_approvals_cover_all_eleven_exact_decisions():
    directories = sorted(path for path in BATCHES.iterdir() if path.is_dir())
    assert [path.name for path in directories] == [
        f"phase7e-2026-batch-{index:02d}" for index in range(1, 12)
    ]
    player_ids = []
    for directory in directories:
        artifact = validate_batch_approval(
            (directory / "approved_envelope.json").read_bytes(),
            (directory / "batch_approval_manifest.json").read_bytes(),
        )
        assert artifact.manifest.reviewer_role == "project_owner"
        assert artifact.manifest.review_date == "2026-08-12"
        player_ids.extend(artifact.manifest.player_ids)
    assert len(player_ids) == len(set(player_ids)) == 108


def test_checked_in_aggregate_is_118_reviewed_resumes_with_honest_completeness():
    artifact = load_aggregate_approval(AGGREGATE)
    assessments = [
        assess_completeness(resume, artifact.envelope)
        for resume in artifact.envelope.resumes
    ]

    assert len(artifact.envelope.resumes) == 118
    assert sum(item.state is CompletenessState.VERIFIED for item in assessments) == 9
    assert sum(item.state is CompletenessState.PARTIAL for item in assessments) == 109
    assert sum(item.state is CompletenessState.NEEDS_REVIEW for item in assessments) == 0
    assert artifact.manifest.reviewer_role == "project_owner"
    assert artifact.manifest.review_date == "2026-08-12"
    assert len(artifact.manifest.approved_batch_ids) == 11


def test_aggregate_manifest_hashes_coverage_and_every_batch_approval():
    artifact = load_aggregate_approval(AGGREGATE)
    coverage = ROOT / "data" / "college_review" / "phase7e" / "roster_coverage_manifest.json"
    assert artifact.manifest.coverage_manifest_sha256 == hashlib.sha256(
        coverage.read_bytes()
    ).hexdigest()
    expected = {
        hashlib.sha256((directory / "batch_approval_manifest.json").read_bytes()).hexdigest()
        for directory in BATCHES.iterdir()
        if directory.is_dir()
    }
    assert set(artifact.manifest.batch_approval_manifest_sha256s) == expected
