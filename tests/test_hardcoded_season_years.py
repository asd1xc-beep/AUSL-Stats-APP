"""Regression coverage for season-map-derived text that must not hardcode a year."""

from __future__ import annotations

import re
from pathlib import Path

import ausl_data
import ausl_stats_app


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
FUTURE_SEASONS = {2025: 270, 2026: 369, 2027: 400}


def test_media_guide_citation_line_follows_the_configured_season_map(monkeypatch):
    monkeypatch.setattr(ausl_data, "SEASONS", FUTURE_SEASONS)

    line = ausl_stats_app.AUSLStatsApp._media_guide_citation_line(None)

    expected_url = ausl_data.media_guide_source_context()["source_url"]
    assert expected_url.endswith("2027-AUSL-Media-Guide.pdf")
    assert line == f"Media guide source: {expected_url}"
    assert "2026" not in line


def test_media_guide_citation_line_matches_current_season_by_default():
    line = ausl_stats_app.AUSLStatsApp._media_guide_citation_line(None)

    expected_url = ausl_data.media_guide_source_context()["source_url"]
    assert line == f"Media guide source: {expected_url}"


def test_clean_game_note_text_strips_season_boilerplate_for_any_configured_year(
    monkeypatch,
):
    monkeypatch.setattr(ausl_data, "SEASONS", FUTURE_SEASONS)
    future_year = max(ausl_data.SEASONS)
    text = f"CHICAGO BANDITS â€¢ {future_year} AUSL Season Notes about Ada Active."

    cleaned = ausl_data._clean_game_note_text(text)

    assert f"{future_year} AUSL Season" not in cleaned
    assert "Notes about Ada Active." in cleaned


def test_clean_game_note_text_still_strips_the_current_season_boilerplate():
    text = "CHICAGO BANDITS â€¢ 2026 AUSL Season Notes about Ada Active."

    cleaned = ausl_data._clean_game_note_text(text)

    assert "2026 AUSL Season" not in cleaned
    assert "Notes about Ada Active." in cleaned


def test_split_game_note_items_strips_single_game_highs_boilerplate_for_any_year(
    monkeypatch,
):
    monkeypatch.setattr(ausl_data, "SEASONS", FUTURE_SEASONS)
    future_year = max(ausl_data.SEASONS)
    page = (
        "#12 - ADA ACTIVE P 5-7 Raleigh, N.C. "
        " â€¢ Needs two hits to reach 50 AUSL career hits "
        f"{future_year} AUSL SEASON SINGLE-GAME HIGHS: 3 RBI"
    )
    lookup = [
        {
            "name": "Ada Active",
            "player_id": "101",
            "team_code": "CHI",
            "key": "ADAACTIVE",
            "first_initial": "A",
            "last_key": "ACTIVE",
        }
    ]

    notes = ausl_data._split_game_note_items(page, lookup)

    assert len(notes) == 1
    assert "SINGLE-GAME HIGHS" not in notes[0]["note_text"]
    assert f"{future_year} AUSL SEASON" not in notes[0]["note_text"]
    assert "Needs two hits to reach 50 AUSL career hits" in notes[0]["note_text"]


def test_split_game_note_items_still_strips_the_current_season_single_game_highs():
    page = (
        "#12 - ADA ACTIVE P 5-7 Raleigh, N.C. "
        " â€¢ Needs two hits to reach 50 AUSL career hits "
        "2026 AUSL SEASON SINGLE-GAME HIGHS: 3 RBI"
    )
    lookup = [
        {
            "name": "Ada Active",
            "player_id": "101",
            "team_code": "CHI",
            "key": "ADAACTIVE",
            "first_initial": "A",
            "last_key": "ACTIVE",
        }
    ]

    notes = ausl_data._split_game_note_items(page, lookup)

    assert len(notes) == 1
    assert "SINGLE-GAME HIGHS" not in notes[0]["note_text"]
    assert "2026 AUSL SEASON" not in notes[0]["note_text"]


def test_game_note_category_recognizes_any_season_year_reference(monkeypatch):
    monkeypatch.setattr(ausl_data, "SEASONS", FUTURE_SEASONS)
    future_year = max(ausl_data.SEASONS)
    note = f"Ada Active has 12 home runs this {future_year} season."

    assert ausl_data._game_note_category(note) == "season_context"


def test_game_note_category_still_recognizes_the_current_season_year_reference():
    note = "Ada Active has 12 home runs this 2026 season."

    assert ausl_data._game_note_category(note) == "season_context"


def test_game_note_category_still_recognizes_supported_season_phrasing():
    assert ausl_data._game_note_category("She is hot this season.") == "season_context"
    assert (
        ausl_data._game_note_category("Her current season average is climbing.")
        == "season_context"
    )
    assert (
        ausl_data._game_note_category("She has a .325 average this AUSL season.")
        == "season_context"
    )


def test_readme_does_not_hardcode_the_current_specific_season_years():
    readme = (Path(__file__).resolve().parents[1] / "README.txt").read_text(
        encoding="utf-8"
    )

    assert "AUSL 2025 and 2026 roster/stat JSON" not in readme
    assert "combine the available 2025 and 2026 AUSL" not in readme
    assert "AUSL CAREER 2025-26" not in readme


ALLOWED_SEASON_YEAR_LINES = (
    (
        "ausl_data.py",
        "SEASONS = {2025: 270, 2026: 369}",
        "the season map definition itself is the single source of truth",
    ),
    (
        "ausl_data.py",
        '"source_url": "https://theausl.com/news/2026-ausl-college-draft-results/"',
        "a specific published article URL that must be reviewed each season",
    ),
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _bare_season_year_pattern():
    years = sorted(str(year) for year in ausl_data.SEASONS)
    return re.compile(r"\b(?:" + "|".join(re.escape(year) for year in years) + r")\b")


def test_no_hardcoded_season_year_literals_outside_the_documented_allowlist():
    season_year_pattern = _bare_season_year_pattern()
    violations = []

    for path in sorted(SRC_DIR.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            iso_date_spans = [match.span() for match in _ISO_DATE.finditer(line)]
            for match in season_year_pattern.finditer(line):
                if any(start <= match.start() < end for start, end in iso_date_spans):
                    continue
                if any(
                    path.name == allowed_file and allowed_snippet in line
                    for allowed_file, allowed_snippet, _reason in ALLOWED_SEASON_YEAR_LINES
                ):
                    continue
                violations.append(f"{path.name}:{lineno}: {line.strip()}")

    assert violations == [], (
        "Found bare season-year literal(s) outside the documented allowlist. "
        "Derive the year from ausl_data.SEASONS, or add a reviewed exception:\n"
        + "\n".join(violations)
    )


def test_allowlist_entries_are_still_present_and_not_stale():
    for filename, snippet, _reason in ALLOWED_SEASON_YEAR_LINES:
        content = (SRC_DIR / filename).read_text(encoding="utf-8")
        assert snippet in content, (
            f"Allowlisted snippet no longer found in {filename}; remove the stale "
            f"entry from ALLOWED_SEASON_YEAR_LINES: {snippet!r}"
        )
