from __future__ import annotations

import io
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from ausl_college_approval import load_checked_in_approval
from ausl_college_scale import (
    COVERAGE_SCHEMA_NAME,
    COVERAGE_SCHEMA_VERSION,
    CoverageState,
    build_batch_manifests,
    build_roster_coverage,
    load_coverage_manifest,
    serialize_coverage_manifest,
    validate_roster_coverage,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
STARTING_SHA = "930217d55cb562a6c18cfa9642c7f0c6858d1d97"


def _starting_workbook(relative: str) -> bytes:
    payload = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "show",
            f"{STARTING_SHA}:{relative}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if payload.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        oid_line = next(
            line
            for line in payload.decode("ascii").splitlines()
            if line.startswith("oid sha256:")
        )
        oid = oid_line.removeprefix("oid sha256:")
        git_dir = Path(
            subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={ROOT}",
                    "rev-parse",
                    "--git-common-dir",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not git_dir.is_absolute():
            git_dir = ROOT / git_dir
        payload = (
            git_dir / "lfs" / "objects" / oid[:2] / oid[2:4] / oid
        ).read_bytes()
    return payload


def _roster(*rows):
    return pd.DataFrame(
        rows,
        columns=(
            "season",
            "player_id",
            "player_name",
            "team_code",
            "roster_status",
            "position",
            "college",
        ),
    )


def test_current_roster_manifest_accounts_for_every_exact_id_and_status():
    roster = pd.read_excel(
        io.BytesIO(_starting_workbook("data/exports/ausl_rosters.xlsx")),
        sheet_name="roster_2026",
    )
    approved = load_checked_in_approval(ROOT / "data" / "college_approved")

    manifest = build_roster_coverage(
        roster,
        season=2026,
        generated_at=NOW,
        approved_artifact=approved,
    )

    assert manifest.schema_name == COVERAGE_SCHEMA_NAME
    assert manifest.schema_version == COVERAGE_SCHEMA_VERSION
    assert len(manifest.entries) == 118
    assert {entry.player_id for entry in manifest.entries} == set(
        roster["player_id"].astype(str)
    )
    assert {entry.roster_status for entry in manifest.entries} == {
        "Active",
        "Reserve Pool",
        "Injured - Temporary",
    }
    totals = manifest.coverage_totals
    assert totals[CoverageState.APPROVED_RESUME_AVAILABLE.value] == 9
    assert totals[CoverageState.REVIEWED_PARTIAL_RESUME.value] == 1
    assert totals[CoverageState.DEVELOPER_REVIEW_PENDING.value] == 108


def test_duplicate_and_missing_player_ids_fail_closed():
    duplicate = _roster(
        (2026, "1", "One", "CHI", "Active", "IF", "Alpha"),
        (2026, "1", "One Again", "TEX", "Reserve Pool", "P", "Beta"),
    )
    missing = _roster(
        (2026, None, "No ID", "CHI", "Active", "IF", "Alpha"),
    )

    with pytest.raises(ValueError, match="duplicate AUSL player ID"):
        build_roster_coverage(duplicate, season=2026, generated_at=NOW)
    with pytest.raises(ValueError, match="missing AUSL player ID"):
        build_roster_coverage(missing, season=2026, generated_at=NOW)


def test_duplicate_names_remain_distinct_and_never_remap_identity():
    roster = _roster(
        (2026, "10", "Same Name", "CHI", "Active", "IF", "Alpha"),
        (2026, "11", "Same Name", "TEX", "Reserve Pool", "P", "Beta"),
    )
    manifest = build_roster_coverage(roster, season=2026, generated_at=NOW)

    assert [entry.player_id for entry in manifest.entries] == ["10", "11"]
    assert all(
        entry.coverage_state is CoverageState.DEVELOPER_REVIEW_PENDING
        for entry in manifest.entries
    )


def test_manifest_is_deterministic_independent_of_roster_row_order():
    roster = _roster(
        (2026, "2", "Beta", "TEX", "Reserve Pool", "P", "Beta U"),
        (2026, "1", "Alpha", "CHI", "Active", "IF", "Alpha U"),
    )
    first = build_roster_coverage(roster, season=2026, generated_at=NOW)
    second = build_roster_coverage(
        roster.iloc[::-1].reset_index(drop=True),
        season=2026,
        generated_at=NOW,
    )

    assert serialize_coverage_manifest(first) == serialize_coverage_manifest(second)
    assert load_coverage_manifest(serialize_coverage_manifest(first)) == first


def test_validation_reports_missing_exact_id_and_name_disagreement_without_remap():
    roster = _roster(
        (2026, "1", "Alpha", "CHI", "Active", "IF", "Alpha U"),
        (2026, "2", "Beta", "TEX", "Reserve Pool", "P", "Beta U"),
    )
    manifest = build_roster_coverage(roster, season=2026, generated_at=NOW)
    changed = _roster(
        (2026, "1", "Wrong Name", "CHI", "Active", "IF", "Alpha U"),
        (2026, "3", "Gamma", "TEX", "Active", "OF", "Gamma U"),
    )

    report = validate_roster_coverage(manifest, changed, season=2026)

    assert not report.valid
    assert report.missing_player_ids == ("3",)
    assert report.extra_player_ids == ("2",)
    assert report.name_disagreements == ("1",)


def test_next_season_builds_a_new_manifest_without_hardcoded_year():
    roster = _roster(
        (2027, "20", "Future Player", "UTA", "Active", "IF", "Future U"),
    )
    manifest = build_roster_coverage(roster, season=2027, generated_at=NOW)

    assert manifest.season == 2027
    assert manifest.manifest_id == "phase7e-roster-coverage-2027-v1"
    assert manifest.entries[0].player_id == "20"


def test_pending_players_are_batched_deterministically_with_safe_limits():
    roster = _roster(
        *((2026, str(i), f"Player {i}", "CHI", "Active", "IF", f"School {i}") for i in range(25))
    )
    manifest = build_roster_coverage(
        roster,
        season=2026,
        generated_at=NOW,
        batch_size=10,
    )
    batches = build_batch_manifests(manifest)

    assert [len(batch.player_ids) for batch in batches] == [10, 10, 5]
    assert [batch.batch_id for batch in batches] == [
        "phase7e-2026-batch-01",
        "phase7e-2026-batch-02",
        "phase7e-2026-batch-03",
    ]
    assert [batch.player_ids for batch in batches] == [
        tuple(str(i) for i in range(10)),
        tuple(str(i) for i in range(10, 20)),
        tuple(str(i) for i in range(20, 25)),
    ]
