from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ausl_data  # noqa: E402  (the local src path is installed above)


@pytest.fixture
def load_fixture():
    def load(name: str):
        return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return load


@pytest.fixture
def roster_rows(load_fixture):
    return load_fixture("roster_statuses.json")


@pytest.fixture
def scoped_note_rows(load_fixture):
    return load_fixture("scoped_manual_notes.json")


@pytest.fixture
def fixture_database(load_fixture, roster_rows):
    stats = load_fixture("season_stats.json")
    context = load_fixture("standings_schedule.json")
    return {
        "roster": pd.DataFrame(roster_rows),
        "batting_2026": pd.DataFrame(stats["batting_2026"]),
        "pitching_2026": pd.DataFrame(stats["pitching_2026"]),
        "fielding_2026": pd.DataFrame(stats["fielding_2026"]),
        "career_batting": pd.DataFrame(stats["career_batting"]),
        "career_pitching": pd.DataFrame(stats["career_pitching"]),
        "career_fielding": pd.DataFrame(stats["career_fielding"]),
        "standings": pd.DataFrame(context["standings"]),
        "schedule_results": pd.DataFrame(context["schedule_results"]),
        "manual_notes": pd.DataFrame(load_fixture("scoped_manual_notes.json")),
        "manifest": {
            "updated_at": "2026-07-18T23:45:00+00:00",
            "source": "fixture-only",
        },
    }


@pytest.fixture(autouse=True)
def block_live_network(monkeypatch):
    """Fail fast if a default test accidentally tries to use the internet."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("Live network access is forbidden in the offline test suite")

    monkeypatch.setattr(ausl_data, "_get_json", blocked)
    monkeypatch.setattr(ausl_data, "_get_text", blocked)
    monkeypatch.setattr(ausl_data, "urlopen", blocked)
