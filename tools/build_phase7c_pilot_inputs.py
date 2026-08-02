"""Build the checked-in normalized Phase 7C manifest and review staging.

The values below are deliberately small, source-linked review records. This
tool performs no network access and grants no approval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STAMP = "2026-08-02T01:39:16+00:00"
ROSTER_SOURCE = "ausl-roster-2026"


PLAYERS = (
    ("950", "Valerie Cagle", "CAR", "Active", "two_way", ("ausl_veteran", "single_school", "two_way", "award_or_record"), "Clemson two-way career with authoritative career tables."),
    ("278", "Rachel Garcia", "TEX", "Active", "two_way", ("ausl_veteran", "single_school", "two_way", "award_or_record", "wcws_or_championship"), "UCLA two-way national award winner and champion."),
    ("1327", "NiJaree Canady", "TEX", "Active", "two_way", ("early_career", "multi_school", "pitcher", "two_way", "award_or_record", "wcws_or_championship"), "Stanford-to-Texas Tech transfer with separate pitching and batting evidence."),
    ("929", "Jocelyn Alo", "CHI", "Inactive - Excused", "hitter", ("ausl_veteran", "single_school", "hitter", "award_or_record", "wcws_or_championship"), "Oklahoma career record holder with authoritative totals."),
    ("1324", "Karlyn Pickens", "CAR", "Active", "pitcher", ("early_career", "single_school", "pitcher", "award_or_record", "wcws_or_championship"), "Tennessee pitcher with recent official season evidence."),
    ("169", "Odicci Alexander-Bennett", "CHI", "Active", "two_way", ("ausl_veteran", "single_school", "two_way", "wcws_or_championship"), "James Madison two-way WCWS résumé."),
    ("1285", "Kelly Maxwell", "PDX", "Active", "pitcher", ("multi_school", "pitcher", "award_or_record", "wcws_or_championship"), "Oklahoma State-to-Oklahoma transfer and 2024 champion."),
    ("1102", "Korbe Otis", "PDX", "Active", "hitter", ("multi_school", "hitter", "award_or_record", "wcws_or_championship"), "Louisville-to-Florida hitter with final-season official totals."),
    ("1322", "Ailana Agbayani", "CHI", "Active", "two_way", ("early_career", "multi_school", "hitter", "pitcher", "two_way", "incomplete_or_conflicting"), "BYU-to-Oklahoma two-way history; pitching career scope intentionally remains incomplete."),
    ("933", "Kayla Kowalik", "CAR", "Injured - Temporary", "hitter", ("single_school", "hitter", "award_or_record"), "Kentucky hitter and program record holder."),
)


SOURCE_SPECS = {
    "clemson-cagle-career": ("official_school_athletics", "Clemson University Athletics", "Individual Career History", "https://data.clemsontigers.com/pdf/softball/2023-24/Career.pdf", "page 3, Valerie Cagle career tables", "2024"),
    "ucla-garcia-bio": ("official_school_athletics", "UCLA Athletics", "Rachel Garcia 2021 roster biography", "https://uclabruins.com/sports/softball/roster/player/rachel-garcia", "2021 biography and statistics", "2021"),
    "ttu-canady-bio": ("official_school_athletics", "Texas Tech Athletics", "NiJaree Canady roster biography", "https://texastech.com/sports/softball/roster/canady-nijaree/13952", "2025 season and prior-to-Texas-Tech sections", "2025"),
    "ou-alo-bio": ("official_school_athletics", "University of Oklahoma Athletics", "Jocelyn Alo 2022 roster biography", "https://soonersports.com/sports/softball/roster/jocelyn-alo/14888", "career record book and TOTAL statistics row", "2022"),
    "ut-pickens-bio": ("official_school_athletics", "University of Tennessee Athletics", "Karlyn Pickens roster biography", "https://utsports.com/sports/softball/roster/karlyn-pickens/22431", "2025 junior season and honors", "2025"),
    "jmu-alexander-bio": ("official_school_athletics", "James Madison University Athletics", "Odicci Alexander roster biography", "https://jmusports.com/sports/softball/roster/odicci-alexander/16460", "2021 redshirt-senior section", "2021"),
    "ou-maxwell-bio": ("official_school_athletics", "University of Oklahoma Athletics", "Kelly Maxwell 2024 roster biography", "https://soonersports.com/sports/softball/roster/kelly-maxwell/16713", "career and 2023 Oklahoma State sections", "2024"),
    "uf-otis-bio": ("official_school_athletics", "University of Florida Athletics", "Korbe Otis roster biography", "https://floridagators.com/sports/softball/roster/korbe-otis/17185", "career honors and 2025 statistics", "2025"),
    "ou-agbayani-bio": ("official_school_athletics", "University of Oklahoma Athletics", "Ailana Agbayani 2026 roster biography", "https://soonersports.com/sports/softball/roster/ailana-agbayani/19763", "career statline and BYU/Oklahoma season sections", "2026"),
    "byu-agbayani-bio": ("official_school_athletics", "BYU Athletics", "Ailana Agbayani 2024 roster biography", "https://byucougars.com/sports/softball/roster/player/ailana-agbayani", "2023 and 2024 two-way season sections", "2024"),
    "uk-kowalik-bio": ("official_school_athletics", "University of Kentucky Athletics", "Kayla Kowalik roster biography", "https://ukathletics.com/sports/softball/roster/season/2022/player/kayla-kowalik/", "2021-22 biography and record notes", "2022"),
}


PROGRAMS = {
    "950": (("clemson", "Clemson", 1, 2020, 2024, "clemson-cagle-career", ((2020, "shortened"),)),),
    "278": (("ucla", "UCLA", 1, 2017, 2021, "ucla-garcia-bio", ((2020, "redshirt"),)),),
    "1327": (("stanford", "Stanford", 1, 2023, 2024, "ttu-canady-bio", ()), ("texas-tech", "Texas Tech", 2, 2025, 2025, "ttu-canady-bio", ())),
    "929": (("oklahoma", "Oklahoma", 1, 2018, 2022, "ou-alo-bio", ((2020, "shortened"), (2022, "extra_eligibility"))),),
    "1324": (("tennessee", "Tennessee", 1, 2023, 2025, "ut-pickens-bio", ()),),
    "169": (("james-madison", "James Madison", 1, 2017, 2021, "jmu-alexander-bio", ((2020, "shortened"), (2021, "extra_eligibility"))),),
    "1285": (("oklahoma-state", "Oklahoma State", 1, 2019, 2023, "ou-maxwell-bio", ((2019, "redshirt"), (2020, "shortened"))), ("oklahoma", "Oklahoma", 2, 2024, 2024, "ou-maxwell-bio", ())),
    "1102": (("louisville", "Louisville", 1, 2022, 2023, "uf-otis-bio", ()), ("florida", "Florida", 2, 2024, 2025, "uf-otis-bio", ())),
    "1322": (("byu", "BYU", 1, 2023, 2024, "byu-agbayani-bio", ()), ("oklahoma", "Oklahoma", 2, 2025, 2026, "ou-agbayani-bio", ())),
    "933": (("kentucky", "Kentucky", 1, 2019, 2023, "uk-kowalik-bio", ((2020, "shortened"), (2023, "extra_eligibility"))),),
}


RECORDS = {
    "950": (("source_career_batting", "two_way", "clemson", None, "clemson-cagle-career", {"hits": 288, "home_runs": 66, "rbi": 224, "batting_average": "0.379"}), ("source_career_pitching", "two_way", "clemson", None, "clemson-cagle-career", {"innings_outs": 2269, "strikeouts": 819, "wins": 86, "losses": 37, "era": "1.72"})),
    "278": (("season_batting", "two_way", "ucla", 2021, "ucla-garcia-bio", {"home_runs": 13, "rbi": 35, "batting_average": "0.342"}), ("season_pitching", "two_way", "ucla", 2021, "ucla-garcia-bio", {"innings_outs": 409, "strikeouts": 183, "wins": 18, "losses": 3, "era": "1.39"})),
    "1327": (("season_pitching", "two_way", "texas-tech", 2025, "ttu-canady-bio", {"strikeouts": 319, "wins": 34, "losses": 7, "era": "1.11"}), ("season_batting", "two_way", "texas-tech", 2025, "ttu-canady-bio", {"home_runs": 11})),
    "929": (("source_career_batting", "hitter", "oklahoma", None, "ou-alo-bio", {"hits": 343, "home_runs": 122, "rbi": 323, "runs": 281, "batting_average": "0.445"}),),
    "1324": (("season_pitching", "pitcher", "tennessee", 2025, "ut-pickens-bio", {"innings_outs": 680, "strikeouts": 306, "wins": 25, "losses": 11, "era": "1.17"}),),
    "169": (("season_pitching", "two_way", "james-madison", 2021, "jmu-alexander-bio", {"innings_outs": 431, "strikeouts": 204, "wins": 18, "losses": 3}), ("season_batting", "two_way", "james-madison", 2021, "jmu-alexander-bio", {"home_runs": 2, "rbi": 12, "batting_average": "0.317"})),
    "1285": (("season_pitching", "pitcher", "oklahoma-state", 2023, "ou-maxwell-bio", {"innings_outs": 428, "strikeouts": 229, "wins": 16, "losses": 7, "era": "1.91"}),),
    "1102": (("season_batting", "hitter", "florida", 2025, "uf-otis-bio", {"hits": 79, "home_runs": 9, "rbi": 53, "runs": 82, "batting_average": "0.434"}),),
    "1322": (("source_career_batting", "two_way", None, None, "ou-agbayani-bio", {"hits": 229, "home_runs": 18, "rbi": 124, "runs": 180, "batting_average": "0.359"}), ("season_pitching", "two_way", "byu", 2023, "byu-agbayani-bio", {"innings_outs": 95, "strikeouts": 26, "wins": 5, "losses": 3, "era": "2.43"}), ("season_pitching", "two_way", "byu", 2024, "ou-agbayani-bio", {"innings_outs": 69, "strikeouts": 17, "wins": 5, "losses": 2, "era": "5.78"})),
    "933": (("season_batting", "hitter", "kentucky", 2021, "uk-kowalik-bio", {"hits": 100, "runs": 79, "batting_average": "0.495"}),),
}


ACHIEVEMENTS = {
    "950": ("national_award", "2023 USA Softball Collegiate Player of the Year", "2023", "clemson", "clemson-cagle-career"),
    "278": ("championship", "2019 NCAA champion and two-time Honda Cup winner", "2019", "ucla", "ucla-garcia-bio"),
    "1327": ("national_award", "2024 USA Softball Collegiate Player of the Year", "2024", "stanford", "ttu-canady-bio"),
    "929": ("record", "NCAA career home run record: 122", "2022", "oklahoma", "ou-alo-bio"),
    "1324": ("national_award", "2025 Softball America National Pitcher of the Year", "2025", "tennessee", "ut-pickens-bio"),
    "169": ("wcws_appearance", "2021 WCWS All-Tournament Team", "2021", "james-madison", "jmu-alexander-bio"),
    "1285": ("championship", "2024 NCAA champion with Oklahoma", "2024", "oklahoma", "ou-maxwell-bio"),
    "1102": ("national_award", "2024 NFCA First-Team All-American", "2024", "florida", "uf-otis-bio"),
    "1322": None,
    "933": ("record", "Kentucky career runs record reached in 2022", "2022", "kentucky", "uk-kowalik-bio"),
}


RAW_VALUE_OVERRIDES = {
    ("950", "source_career_pitching", None, "innings_outs"): "756.1",
    ("278", "season_pitching", 2021, "innings_outs"): "136.1",
    ("1324", "season_pitching", 2025, "innings_outs"): "226.2",
    ("169", "season_pitching", 2021, "innings_outs"): "143.2",
    ("1285", "season_pitching", 2023, "innings_outs"): "142.2",
    ("1322", "season_pitching", 2023, "innings_outs"): "31.2",
    ("1322", "season_pitching", 2024, "innings_outs"): "23.0",
}


def _source(source_id, spec):
    source_type, organization, title, url, locator, effective = spec
    return {"source_id": source_id, "source_type": source_type, "organization": organization, "title": title, "locator": locator, "retrieved_at": STAMP, "version": "phase7c-normalized-manual-v1", "verification_state": "verified", "url": url, "local_document_id": None, "effective_date": effective, "content_hash": None, "reviewer": None, "approved_at": None, "review_note": "Official-source evidence normalized for developer review; producer review not performed."}


def _record(player_id, index, spec):
    record_type, role, program_id, season, source_id, metrics = spec
    candidates = []
    for metric, value in sorted(metrics.items()):
        raw_value = RAW_VALUE_OVERRIDES.get(
            (player_id, record_type, season, metric), value
        )
        candidates.append({"candidate_id": f"{player_id}-{record_type}-{season or 'career'}-{metric}", "field_path": f"stats.{metric}", "raw_source_value": raw_value, "value": value, "value_state": "present", "source_id": source_id, "player_id": player_id, "program_id": program_id, "season": season, "record_type": record_type, "metric_definition": metric, "unit": "rate" if isinstance(value, str) else "count"})
    return {"record_id": f"{player_id}-{index}-{record_type}", "record_type": record_type, "role": role, "player_id": player_id, "program_id": program_id, "season": season, "candidates": candidates}


def build():
    manifest_entries, resumes = [], []
    for player_id, name, team, status, role, coverage, reason in PLAYERS:
        manifest_entries.append({"player_id": player_id, "display_name": name, "team_code": team, "roster_status": status, "expected_college_role": role, "coverage_categories": list(coverage), "reason": reason, "initial_identity_source_id": ROSTER_SOURCE, "expected_evidence_issue": "College pitching scope intentionally incomplete; producer review required." if player_id == "1322" else None})
        program_rows, stint_rows = [], []
        for program_id, display, order, start, end, source_id, season_kinds in PROGRAMS[player_id]:
            program_rows.append({"program_id": program_id, "display_name": display, "source_ids": [source_id], "source_identifiers": [], "historical_names": []})
            stint_rows.append({"stint_id": f"{player_id}-stint-{order}", "program_id": program_id, "transfer_order": order, "start_season": start, "end_season": end, "provenance_ids": [source_id], "season_kinds": [list(item) for item in season_kinds], "uncertainty_note": None})
        achievement = ACHIEVEMENTS[player_id]
        achievements = [] if achievement is None else [{"achievement_id": f"{player_id}-achievement-1", "achievement_type": achievement[0], "scope": "individual" if achievement[0] != "championship" else "team", "player_id": player_id, "program_id": achievement[3], "season_or_date": achievement[2], "normalized_label": achievement[1], "source_wording": achievement[1], "provenance_ids": [achievement[4]]}]
        resumes.append({"resume_id": f"pilot-resume-{player_id}", "player_id": player_id, "canonical_display_name": name, "display_name_source_id": ROSTER_SOURCE, "identity_mappings": [{"mapping_id": f"identity-{player_id}", "ausl_player_id": player_id, "source_id": ROSTER_SOURCE, "source_athlete_id": f"ausl-roster-{player_id}", "aliases": [], "review_state": "needs_review", "reviewer": None, "reviewed_at": None, "evidence_reference": "Exact canonical AUSL roster ID; human review pending."}], "programs": program_rows, "stints": stint_rows, "stat_records": [_record(player_id, index, spec) for index, spec in enumerate(RECORDS[player_id], 1)], "achievements": achievements, "section_statuses": [["identity", "needs_review"], ["programs", "verified"], ["statistics", "verified"], ["achievements", "unavailable" if not achievements else "verified"]]})
    sources = [_source(source_id, spec) for source_id, spec in sorted(SOURCE_SPECS.items())]
    sources.append({"source_id": ROSTER_SOURCE, "source_type": "official_ausl_player_profile", "organization": "Athletes Unlimited Softball League", "title": "Canonical AUSL 2026 roster export", "locator": "roster_2026 row matched by exact player_id", "retrieved_at": STAMP, "version": "phase7c-roster-crosswalk-v1", "verification_state": "verified", "url": None, "local_document_id": "data/exports/ausl_rosters.xlsx#roster_2026", "effective_date": "2026", "content_hash": None, "reviewer": None, "approved_at": None, "review_note": "Exact local canonical roster identity; human college-identity review pending."})
    manifest = {"schema_name": "ausl-college-pilot-manifest", "schema_version": 1, "pilot_id": "phase7c-ten-player-pilot-v1", "entries": manifest_entries}
    staging = {"schema_name": "ausl-college-pilot-staging", "schema_version": 1, "mode": "developer_review", "generated_at": STAMP, "completeness_profile": "CORE_RESUME_V1", "sources": sources, "resumes": resumes, "validation_metadata": [["phase", "7C"], ["approval", "producer_review_pending"], ["scope", "ten_player_pilot"]]}
    return manifest, staging


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest, staging = build()
    for path, value in ((args.manifest, manifest), (args.staging, staging)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
