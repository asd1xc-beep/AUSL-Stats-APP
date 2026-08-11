import pytest

from phase7c_fixtures import REQUIRED_COVERAGE, copy, manifest_dict, roster_frame
from ausl_college_import import load_pilot_manifest, validate_pilot_manifest


def parsed_manifest(value=None):
    import json
    return load_pilot_manifest(json.dumps(value or manifest_dict()).encode())


def test_exactly_ten_distinct_canonical_ids_cover_required_cohort():
    report = validate_pilot_manifest(parsed_manifest(), roster_frame())
    assert report.valid
    assert report.accepted_player_ids == tuple(str(7000 + i) for i in range(10))
    assert set(report.coverage_categories) >= set(REQUIRED_COVERAGE)


@pytest.mark.parametrize("count", [9, 11])
def test_nine_or_eleven_entries_are_rejected(count):
    report = validate_pilot_manifest(parsed_manifest(manifest_dict(count)), roster_frame(count))
    assert not report.valid
    assert any("exactly ten" in item for item in report.errors)


def test_unknown_duplicate_and_name_only_identity_fail_closed():
    unknown = manifest_dict()
    unknown["entries"][0]["player_id"] = "999999"
    assert not validate_pilot_manifest(parsed_manifest(unknown), roster_frame()).valid
    duplicate = manifest_dict()
    duplicate["entries"][1]["player_id"] = duplicate["entries"][0]["player_id"]
    assert not validate_pilot_manifest(parsed_manifest(duplicate), roster_frame()).valid
    name_only = manifest_dict()
    del name_only["entries"][0]["player_id"]
    with pytest.raises(ValueError, match="player_id"):
        parsed_manifest(name_only)


def test_display_name_disagreement_reports_review_and_never_remaps_id():
    value = manifest_dict()
    value["entries"][0]["display_name"] = "Different Person"
    report = validate_pilot_manifest(parsed_manifest(value), roster_frame())
    assert not report.valid
    assert report.accepted_player_ids[0] == "7000"
    assert any("display name" in item.casefold() for item in report.errors)


def test_duplicate_names_remain_distinct_by_id_and_missing_coverage_fails():
    roster = roster_frame()
    roster.loc[1, "player_name"] = roster.loc[0, "player_name"]
    value = manifest_dict()
    value["entries"][1]["display_name"] = value["entries"][0]["display_name"]
    assert validate_pilot_manifest(parsed_manifest(value), roster).valid
    missing = manifest_dict()
    for entry in missing["entries"]:
        entry["coverage_categories"] = [
            item for item in entry["coverage_categories"] if item != "two_way"
        ]
        if not entry["coverage_categories"]:
            entry["coverage_categories"] = ["hitter"]
    report = validate_pilot_manifest(parsed_manifest(missing), roster_frame())
    assert not report.valid
    assert any("two_way" in item for item in report.errors)


def test_unknown_manifest_fields_are_rejected():
    value = manifest_dict()
    value["shortcut_approval"] = True
    with pytest.raises(ValueError, match="unknown"):
        parsed_manifest(value)
