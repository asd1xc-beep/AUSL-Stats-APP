from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

import ausl_data
from ausl_enrichment import official_note_approval_record_id
from tools.build_distribution_profile import stage_distribution_profile
from tools.create_portable_zip import create_portable_zip
from tools.generate_distribution_manifest import generate_distribution_manifest
from tools.verify_distribution import scan_distribution


ROOT = Path(__file__).resolve().parents[1]
CORE_NAMES = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
    "update_manifest.json",
    "refresh_attempt.json",
)


def _source_exports(tmp_path: Path, *, with_optional: bool) -> Path:
    source = tmp_path / "source-exports"
    source.mkdir()
    checked_in = ROOT / "data" / "exports"
    for name in CORE_NAMES:
        shutil.copyfile(checked_in / name, source / name)
    manifest = json.loads((source / "update_manifest.json").read_text(encoding="utf-8"))
    manifest["source_health"].update(
        {
            "official_game_notes": {"status": "green"},
            "media_guide": {"status": "green"},
            "split_stats": {"status": "green"},
        }
    )
    (source / "update_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    generate_distribution_manifest(source)
    if not with_optional:
        return source

    roster = pd.read_excel(
        source / "ausl_rosters.xlsx", sheet_name="roster_2026"
    )
    player = roster[
        roster["player_id"].notna()
        & roster["player_name"].notna()
        & roster["team_code"].notna()
    ].iloc[0]
    player_id = str(int(player["player_id"]))
    team_code = str(player["team_code"]).upper()
    opposing = next(code for code in ("CHI", "CAR", "TAL", "VOL") if code != team_code)
    note = {
        "game_id": 9001,
        "source_game_id": 9001,
        "game_date": "2026-07-29",
        "source_date": "2026-07-29",
        "team_codes": f"{team_code},{opposing}",
        "subject_player_id": player_id,
        "subject_player_name": str(player["player_name"]),
        "subject_team_code": team_code,
        "opposing_team_code": opposing,
        "note_text": f"{player['player_name']} has reached an official AUSL milestone.",
        "note_category": "milestone_reached",
        "source_url": "https://theausl.com/notes/9001.pdf",
        "source_pdf": "9001.pdf",
        "source_page": 4,
        "parser_version": "official-game-notes-v1",
        "normalized_hash": ausl_data._normalized_game_note_hash(
            f"{player['player_name']} has reached an official AUSL milestone."
        ),
        "verification_state": "VERIFIED",
        "needs_review": False,
        "approval_state": "approved",
        "approval_method": "manual_review",
        "approved_by": "Fixture Producer",
        "approved_at": "2026-07-29T12:00:00+00:00",
    }
    note["approval_record_id"] = official_note_approval_record_id(note)
    ausl_data._write_excel_atomic(
        source / "official_game_notes.xlsx",
        {"official_game_notes": pd.DataFrame([note])},
    )
    split = pd.DataFrame(
        [
            {
                "player_id": player_id,
                "season": 2026,
                "split_key": "last7Days",
                "split_label": "Last 7 Days",
                "plateAppearances": 12,
                "hits": 5,
                "battingAverage": 0.417,
                "source_name": "Official AUSL Split Stats",
                "source_url": "https://theausl.com/splits",
                "imported_at": "2026-07-29T12:00:00+00:00",
            }
        ]
    )
    ausl_data._write_excel_atomic(
        source / "ausl_batting_splits.xlsx", {"batting_splits": split}
    )
    return source


def test_default_core_profile_stays_unchanged_and_rejects_optional_files(tmp_path):
    source = _source_exports(tmp_path, with_optional=True)
    destination = tmp_path / "core"

    stage_distribution_profile(source, destination, profile="core")

    assert scan_distribution(destination, profile="core") == []
    assert not (destination / "official_game_notes.xlsx").exists()
    assert not (destination / "approved_enrichment_manifest.json").exists()


def test_approved_profile_contains_only_filtered_rows_and_verifies(tmp_path):
    source = _source_exports(tmp_path, with_optional=True)
    destination = tmp_path / "approved"

    stage_distribution_profile(
        source, destination, profile="approved-enrichment"
    )

    assert scan_distribution(destination, profile="approved-enrichment") == []
    approved_notes = pd.read_excel(
        destination / "official_game_notes.xlsx",
        sheet_name="official_game_notes",
    )
    assert len(approved_notes) == 1
    assert set(approved_notes["producer_approved"]) == {True}
    manifest = json.loads(
        (destination / "approved_enrichment_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["profile"] == "approved-enrichment"
    assert manifest["approval_schema_version"] == 1
    assert manifest["row_counts"]["official_game_notes"] == 1
    assert not any("raw" in record["name"] for record in manifest["files"])


def test_core_verifier_rejects_explicit_enrichment_profile(tmp_path):
    source = _source_exports(tmp_path, with_optional=True)
    destination = tmp_path / "approved"
    stage_distribution_profile(
        source, destination, profile="approved-enrichment"
    )

    violations = scan_distribution(destination, profile="core")

    assert any("unverified enrichment" in item.reason for item in violations)


def test_approved_profile_verifier_catches_injected_row(tmp_path):
    source = _source_exports(tmp_path, with_optional=True)
    destination = tmp_path / "approved"
    stage_distribution_profile(
        source, destination, profile="approved-enrichment"
    )
    notes_path = destination / "official_game_notes.xlsx"
    notes = pd.read_excel(notes_path, sheet_name="official_game_notes")
    injected = pd.concat(
        [
            notes,
            pd.DataFrame(
                [
                    {
                        "note_text": "Unreviewed injected row",
                        "needs_review": True,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    ausl_data._write_excel_atomic(
        notes_path, {"official_game_notes": injected}
    )

    violations = scan_distribution(
        destination, profile="approved-enrichment"
    )

    assert any(
        "hash mismatch" in item.reason or "approval gate" in item.reason
        for item in violations
    )


def test_missing_optional_sources_produces_valid_core_fallback_profile(tmp_path):
    source = _source_exports(tmp_path, with_optional=False)
    destination = tmp_path / "approved-empty"

    stage_distribution_profile(
        source, destination, profile="approved-enrichment"
    )

    assert scan_distribution(destination, profile="approved-enrichment") == []
    manifest = json.loads(
        (destination / "approved_enrichment_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["row_counts"] == {}
    assert manifest["fallback"] == "core_only"


def test_approved_profile_zip_is_portable_and_deterministic(tmp_path):
    source = _source_exports(tmp_path, with_optional=True)
    first_stage = tmp_path / "first-stage"
    second_stage = tmp_path / "second-stage"
    stage_distribution_profile(
        source, first_stage, profile="approved-enrichment"
    )
    stage_distribution_profile(
        source, second_stage, profile="approved-enrichment"
    )
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    create_portable_zip(first_stage, first_zip)
    create_portable_zip(second_stage, second_zip)

    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert scan_distribution(
        first_zip, profile="approved-enrichment"
    ) == []
