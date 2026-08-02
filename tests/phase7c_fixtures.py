from __future__ import annotations

from copy import deepcopy

import pandas as pd


REQUIRED_COVERAGE = (
    "early_career",
    "ausl_veteran",
    "single_school",
    "multi_school",
    "hitter",
    "pitcher",
    "two_way",
    "award_or_record",
    "wcws_or_championship",
    "incomplete_or_conflicting",
)


def roster_frame(count=10):
    return pd.DataFrame(
        [
            {
                "player_id": 7000 + index,
                "player_name": f"Synthetic Player {index}",
                "team_code": "TST",
                "roster_status": "Active",
                "position": "UTIL" if index == 2 else "RHP" if index == 1 else "IF",
            }
            for index in range(count)
        ]
    )


def manifest_dict(count=10):
    entries = []
    for index in range(count):
        categories = [
            REQUIRED_COVERAGE[index]
            if index < len(REQUIRED_COVERAGE)
            else "early_career"
        ]
        if index == 2:
            categories.extend(("hitter", "pitcher"))
        entries.append(
            {
                "player_id": str(7000 + index),
                "display_name": f"Synthetic Player {index}",
                "team_code": "TST",
                "roster_status": "Active",
                "expected_college_role": "two_way" if index == 2 else "pitcher" if index == 1 else "hitter",
                "coverage_categories": categories,
                "reason": "Clearly synthetic pilot fixture.",
                "initial_identity_source_id": f"source-{index}",
                "expected_evidence_issue": "conflict expected" if index == 9 else None,
            }
        )
    return {
        "schema_name": "ausl-college-pilot-manifest",
        "schema_version": 1,
        "pilot_id": "synthetic-ten-player-pilot",
        "entries": entries,
    }


def staging_dict(count=10):
    sources = []
    resumes = []
    for index in range(count):
        player_id = str(7000 + index)
        source_id = f"source-{index}"
        sources.append(
            {
                "source_id": source_id,
                "source_type": "official_school_athletics",
                "organization": f"Synthetic University {index}",
                "title": "Synthetic official biography",
                "locator": "identity and college section",
                "retrieved_at": "2026-08-02T12:00:00+00:00",
                "version": "phase7c-fixture-v1",
                "verification_state": "verified",
                "url": f"https://example.invalid/player-{index}",
                "local_document_id": None,
                "effective_date": "2025",
                "content_hash": None,
                "reviewer": None,
                "approved_at": None,
                "review_note": "Synthetic official-source fixture; not producer approved.",
            }
        )
        role = "two_way" if index == 2 else "pitcher" if index == 1 else "hitter"
        record_type = "season_pitching" if role == "pitcher" else "season_batting"
        metric = "innings_outs" if role == "pitcher" else "hits"
        value = 0 if index == 8 else 20 + index
        resumes.append(
            {
                "resume_id": f"pilot-resume-{player_id}",
                "player_id": player_id,
                "canonical_display_name": f"Synthetic Player {index}",
                "display_name_source_id": source_id,
                "identity_mappings": [
                    {
                        "mapping_id": f"identity-{player_id}",
                        "ausl_player_id": player_id,
                        "source_id": source_id,
                        "source_athlete_id": f"school-{player_id}",
                        "aliases": [],
                        "review_state": "needs_review",
                        "reviewer": None,
                        "reviewed_at": None,
                        "evidence_reference": "Exact AUSL ID roster reconciliation; human review pending.",
                    }
                ],
                "programs": [
                    {
                        "program_id": f"synthetic-university-{index}",
                        "display_name": f"Synthetic University {index}",
                        "source_ids": [source_id],
                        "source_identifiers": [],
                        "historical_names": [],
                    }
                ],
                "stints": [
                    {
                        "stint_id": f"stint-{player_id}",
                        "program_id": f"synthetic-university-{index}",
                        "transfer_order": 1,
                        "start_season": 2024,
                        "end_season": 2025,
                        "provenance_ids": [source_id],
                        "season_kinds": [[2025, "standard"]],
                        "uncertainty_note": None,
                    }
                ],
                "stat_records": [
                    {
                        "record_id": f"record-{player_id}",
                        "record_type": record_type,
                        "role": role,
                        "player_id": player_id,
                        "program_id": f"synthetic-university-{index}",
                        "season": 2025,
                        "candidates": [
                            {
                                "candidate_id": f"candidate-{player_id}",
                                "field_path": f"stats.{metric}",
                                "raw_source_value": value,
                                "value": value,
                                "value_state": "present",
                                "source_id": source_id,
                                "player_id": player_id,
                                "program_id": f"synthetic-university-{index}",
                                "season": 2025,
                                "record_type": record_type,
                                "metric_definition": metric,
                                "unit": "count",
                            }
                        ],
                    }
                ],
                "achievements": [],
                "section_statuses": [
                    ["identity", "needs_review"],
                    ["programs", "verified"],
                    ["statistics", "verified"],
                    ["achievements", "unavailable"],
                ],
            }
        )
    return {
        "schema_name": "ausl-college-pilot-staging",
        "schema_version": 1,
        "mode": "developer_review",
        "generated_at": "2026-08-02T12:00:00+00:00",
        "completeness_profile": "CORE_RESUME_V1",
        "sources": sources,
        "resumes": resumes,
        "validation_metadata": [["fixture", "synthetic"]],
    }


def copy(value):
    return deepcopy(value)
