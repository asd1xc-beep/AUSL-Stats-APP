from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import ausl_data


LEGACY_CSV = (
    "note_id,player_id,player_name,team_code,note_text,note_type,entered_by,source,"
    "last_verified_date,air_safe,created_at,legacy_extra\n"
    "1,101,Ada Active,CHI,Exact player note,producer,producer,manual,,False,"
    "2026-07-18T20:00:00+00:00,keep-me\n"
    "2,,,CHI,Explicit team note,producer,producer,manual,,False,"
    "2026-07-18T20:01:00+00:00,keep-team\n"
    "3,,,,Unassigned legacy note,producer,producer,manual,,False,"
    "2026-07-18T20:02:00+00:00,keep-unknown\n"
)


def test_manual_note_migration_backs_up_exact_bytes_and_preserves_rows(tmp_path):
    path = tmp_path / "player_notes.csv"
    original = LEGACY_CSV.encode("utf-8")
    path.write_bytes(original)

    migrated, backup_path = ausl_data.migrate_manual_notes_file(path)

    assert backup_path is not None
    assert Path(backup_path).read_bytes() == original
    assert len(migrated) == 3
    assert migrated["scope"].tolist() == ["player", "team", "legacy_unassigned"]
    assert migrated["legacy_extra"].tolist() == ["keep-me", "keep-team", "keep-unknown"]
    assert {"game_id", "updated_at", "author"}.issubset(migrated.columns)
    reloaded = pd.read_csv(path, keep_default_na=False)
    assert len(reloaded) == 3
    assert reloaded["scope"].tolist() == ["player", "team", "legacy_unassigned"]


def test_atomic_manual_note_write_preserves_original_on_generation_failure(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "player_notes.csv"
    path.write_bytes(b"original-bytes\n")
    frame = pd.DataFrame([{"note_id": 1, "scope": "global", "note_text": "safe"}])

    def fail_to_csv(self, *args, **kwargs):
        raise RuntimeError("fixture write failure")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(RuntimeError, match="fixture write failure"):
        ausl_data.write_manual_notes_atomic(path, frame)

    assert path.read_bytes() == b"original-bytes\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_current_manual_note_schema_is_not_rewritten_or_backed_up(tmp_path):
    path = tmp_path / "player_notes.csv"
    frame = pd.DataFrame(
        [
            {
                "note_id": 1,
                "scope": "player",
                "player_id": 101,
                "player_name": "Ada Active",
                "team_code": "CHI",
                "game_id": "",
                "note_text": "Current row",
                "created_at": "2026-07-18T20:00:00+00:00",
                "updated_at": "2026-07-18T20:00:00+00:00",
                "author": "producer",
                "source": "manual",
            }
        ]
    )
    frame.to_csv(path, index=False)
    original = path.read_bytes()

    migrated, backup_path = ausl_data.migrate_manual_notes_file(path)

    assert backup_path is None
    assert path.read_bytes() == original
    assert len(migrated) == 1
