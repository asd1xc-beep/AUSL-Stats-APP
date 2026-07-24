from __future__ import annotations

from pathlib import Path

import pandas as pd

import ausl_stats_app


def selector():
    assert hasattr(ausl_stats_app, "select_manual_notes"), (
        "Phase 1 requires ausl_stats_app.select_manual_notes"
    )
    return ausl_stats_app.select_manual_notes


def selected_ids(frame):
    assert isinstance(frame, pd.DataFrame)
    return set(pd.to_numeric(frame["note_id"], errors="raise").astype(int))


def test_player_context_combines_exact_player_team_and_game_scopes(scoped_note_rows):
    notes = pd.DataFrame(scoped_note_rows)

    selected = selector()(
        notes,
        player_id=101,
        team_code="CHI",
        game_id="9001",
    )

    assert selected_ids(selected) == {1, 3, 4}


def test_player_without_private_note_never_inherits_a_teammates_note(scoped_note_rows):
    notes = pd.DataFrame(scoped_note_rows)

    selected = selector()(
        notes,
        player_id=999,
        team_code="CHI",
        game_id="9001",
    )

    assert selected_ids(selected) == {3, 4}
    assert 1 not in selected_ids(selected)
    assert 2 not in selected_ids(selected)


def test_team_view_returns_only_explicit_team_scope(scoped_note_rows):
    notes = pd.DataFrame(scoped_note_rows)

    selected = selector()(notes, team_code="CHI")

    assert selected_ids(selected) == {3}


def test_global_notes_require_an_explicit_opt_in(scoped_note_rows):
    notes = pd.DataFrame(scoped_note_rows)

    without_global = selector()(notes, player_id=101, team_code="CHI")
    with_global = selector()(
        notes,
        player_id=101,
        team_code="CHI",
        include_global=True,
    )

    assert 5 not in selected_ids(without_global)
    assert selected_ids(with_global) == {1, 3, 5}


def test_renderer_does_not_drop_team_note_after_many_exact_player_notes():
    rows = [
        {
            "note_id": index,
            "scope": "player",
            "player_id": 101,
            "team_code": "CHI",
            "game_id": "",
            "note_text": f"Player note {index}",
            "source": "manual",
            "updated_at": f"2026-07-19T00:0{index}:00+00:00",
        }
        for index in range(1, 7)
    ]
    rows.append(
        {
            "note_id": 7,
            "scope": "team",
            "player_id": "",
            "team_code": "CHI",
            "game_id": "",
            "note_text": "Team-wide availability warning",
            "source": "manual",
            "updated_at": "2026-07-19T00:07:00+00:00",
        }
    )
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"manual_notes": pd.DataFrame(rows)}

    lines = app._manual_note_lines(player_id=101, team_code="CHI")

    assert len(lines) == 7
    assert any("[TEAM" in line and "Team-wide availability warning" in line for line in lines)


def test_legacy_unscoped_note_is_not_guessed_into_a_player_or_team_scope(scoped_note_rows):
    notes = pd.DataFrame(scoped_note_rows)

    selected = selector()(notes, player_id=101, team_code="CHI", include_global=True)

    assert 6 not in selected_ids(selected)


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeText:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def delete(self, *_args):
        self.value = ""


def manual_note_app(tmp_path: Path, roster: pd.DataFrame):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "roster": roster,
        "schedule_results": pd.DataFrame([{"game_id": "9001"}]),
        "manual_notes": pd.DataFrame(),
    }
    app.note_scope_var = FakeVar("player")
    app.note_player_var = FakeVar("")
    app.note_team_var = FakeVar("")
    app.note_game_var = FakeVar("")
    app.note_type_var = FakeVar("producer")
    app.note_author_var = FakeVar("producer")
    app.note_air_safe_var = FakeVar(False)
    app.note_text = FakeText("Producer context")
    app.manual_note_status = FakeVar()
    app.manual_notes_path = lambda: tmp_path / "player_notes.csv"
    app.render_manual_notes = lambda: None
    return app


def test_ambiguous_typed_player_blocks_manual_note_save(tmp_path):
    roster = pd.DataFrame(
        [
            {"player_id": 101, "player_name": "Same Name", "team_code": "CHI"},
            {"player_id": 202, "player_name": "Same Name", "team_code": "CAR"},
        ]
    )
    app = manual_note_app(tmp_path, roster)
    app.note_player_var.set("Same Name")

    app.save_manual_note()

    assert "multiple" in app.manual_note_status.get().lower()
    assert not app.manual_notes_path().exists()


def test_exact_player_picker_save_is_scoped_and_atomic_and_preserves_columns(
    tmp_path,
    roster_rows,
):
    app = manual_note_app(tmp_path, pd.DataFrame(roster_rows))
    app.note_player_var.set("Ada Active | CHI | ID 101")
    path = app.manual_notes_path()
    existing = pd.DataFrame(
        [
            {
                "note_id": 7,
                "scope": "team",
                "player_id": "",
                "player_name": "",
                "team_code": "CHI",
                "game_id": "",
                "note_text": "Existing context",
                "author": "talent",
                "source": "manual",
                "created_at": "2026-07-18T20:00:00+00:00",
                "updated_at": "2026-07-18T20:01:00+00:00",
                "legacy_extra": "preserve-me",
            }
        ]
    )
    existing.to_csv(path, index=False)

    app.save_manual_note()

    saved = pd.read_csv(path, dtype=object, keep_default_na=False)
    assert len(saved) == 2
    assert saved.iloc[0]["legacy_extra"] == "preserve-me"
    assert saved.iloc[0]["author"] == "talent"
    new = saved.iloc[1]
    assert new["scope"] == "player"
    assert new["player_id"] == "101"
    assert new["player_name"] == "Ada Active"
    assert new["team_code"] == "CHI"
    assert new["game_id"] == ""
    assert new["author"] == "producer"
    assert new["source"] == "manual"
    assert new["created_at"]
    assert new["updated_at"] == new["created_at"]


def test_unresolved_game_id_blocks_game_scoped_note_save(tmp_path, roster_rows):
    app = manual_note_app(tmp_path, pd.DataFrame(roster_rows))
    app.note_scope_var.set("game")
    app.note_game_var.set("9999")

    app.save_manual_note()

    assert "official schedule" in app.manual_note_status.get().lower()
    assert not app.manual_notes_path().exists()
