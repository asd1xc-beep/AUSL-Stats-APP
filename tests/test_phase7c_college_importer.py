from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from phase7c_fixtures import copy, manifest_dict, roster_frame, staging_dict
from ausl_college import SCHEMA_VERSION, load_envelope, validate_envelope
from ausl_college_import import import_college_pilot, load_staging


def write_inputs(tmp_path, *, staging=None, manifest=None):
    roster_path = tmp_path / "roster.xlsx"
    with pd.ExcelWriter(roster_path, engine="openpyxl") as writer:
        roster_frame().to_excel(writer, sheet_name="roster_2026", index=False)
    manifest_path = tmp_path / "pilot-manifest.json"
    manifest_path.write_text(json.dumps(manifest or manifest_dict()), encoding="utf-8")
    staging_path = tmp_path / "staging.json"
    staging_path.write_text(json.dumps(staging or staging_dict()), encoding="utf-8")
    return roster_path, manifest_path, staging_path


def run_import(tmp_path, **kwargs):
    roster, manifest, staging = write_inputs(tmp_path, **kwargs)
    output = tmp_path / "pilot-envelope.json"
    report = tmp_path / "review.md"
    result = import_college_pilot(roster, manifest, staging, output, report)
    return result, output, report


def test_developer_review_import_produces_phase7b_envelope_and_report(tmp_path):
    result, output, report = run_import(tmp_path)
    envelope = load_envelope(output.read_bytes())
    assert result.promoted
    assert envelope.schema_version == SCHEMA_VERSION
    assert len(envelope.resumes) == len(envelope.sources) == 10
    assert "air-ready" not in report.read_text(encoding="utf-8").casefold()
    assert "PRODUCER REVIEW PENDING" in report.read_text(encoding="utf-8")


def test_exact_identity_pending_human_review_is_valid_but_not_complete(tmp_path):
    _result, output, report = run_import(tmp_path)
    validation = validate_envelope(load_envelope(output.read_bytes()))
    assert validation.valid
    assert len(validation.unresolved_identities) == 10
    assert any("human review pending" in item for item in validation.warnings)
    assert "identity_review_pending" in report.read_text(encoding="utf-8")


def test_repeated_import_is_byte_identical_and_idempotent(tmp_path):
    _result, output, report = run_import(tmp_path)
    first = (output.read_bytes(), report.read_bytes())
    roster = tmp_path / "roster.xlsx"
    manifest = tmp_path / "pilot-manifest.json"
    staging = tmp_path / "staging.json"
    import_college_pilot(roster, manifest, staging, output, report)
    assert first == (output.read_bytes(), report.read_bytes())


def test_failure_preserves_last_known_good_outputs(tmp_path):
    _result, output, report = run_import(tmp_path)
    before = (output.read_bytes(), report.read_bytes())
    bad = staging_dict()
    bad["resumes"][0]["player_id"] = "unknown-id"
    (tmp_path / "staging.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        import_college_pilot(tmp_path / "roster.xlsx", tmp_path / "pilot-manifest.json", tmp_path / "staging.json", output, report)
    assert before == (output.read_bytes(), report.read_bytes())


def test_mid_promotion_failure_rolls_back_both_outputs_and_cleans_temps(tmp_path):
    _result, output, report = run_import(tmp_path)
    before = (output.read_bytes(), report.read_bytes())
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("forced second promotion failure")
        Path(source).replace(destination)

    with pytest.raises(OSError, match="forced second promotion failure"):
        import_college_pilot(
            tmp_path / "roster.xlsx",
            tmp_path / "pilot-manifest.json",
            tmp_path / "staging.json",
            output,
            report,
            replace_func=fail_second_replace,
        )

    assert before == (output.read_bytes(), report.read_bytes())
    assert not list(tmp_path.glob(".*.tmp"))


def test_wrong_mode_unknown_fields_and_duplicate_ids_are_rejected(tmp_path):
    for mutate in (
        lambda value: value.update(mode="producer_approved"),
        lambda value: value.update(approval_shortcut=True),
        lambda value: value["sources"].append(copy(value["sources"][0])),
        lambda value: value["resumes"][1]["stat_records"][0]["candidates"].append(copy(value["resumes"][0]["stat_records"][0]["candidates"][0])),
    ):
        value = staging_dict()
        mutate(value)
        with pytest.raises(ValueError):
            load_staging(json.dumps(value).encode())


def test_staging_requires_raw_source_value_separate_from_normalized_value():
    value = staging_dict()
    candidate = value["resumes"][0]["stat_records"][0]["candidates"][0]
    candidate.pop("raw_source_value")
    with pytest.raises(ValueError, match="raw_source_value"):
        load_staging(json.dumps(value).encode())

    value = staging_dict()
    candidate = value["resumes"][1]["stat_records"][0]["candidates"][0]
    candidate["raw_source_value"] = "6.2 IP"
    candidate["value"] = 20
    staging = load_staging(json.dumps(value).encode())
    normalized = staging.envelope.resumes[1].stat_records[0].candidates[0]
    assert normalized.value == 20


def test_explicit_zero_remains_distinct_from_missing():
    value = staging_dict()
    zero_candidate = value["resumes"][8]["stat_records"][0]["candidates"][0]
    assert zero_candidate["value"] == 0
    missing_candidate = value["resumes"][9]["stat_records"][0]["candidates"][0]
    missing_candidate["raw_source_value"] = None
    missing_candidate["value"] = None
    missing_candidate["value_state"] = "missing"
    envelope = load_staging(json.dumps(value).encode()).envelope
    assert envelope.resumes[8].stat_records[0].candidates[0].value == 0
    assert envelope.resumes[9].stat_records[0].candidates[0].value is None


def test_no_network_or_producer_approval_generated(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network forbidden")))
    _result, output, _report = run_import(tmp_path)
    text = output.read_text(encoding="utf-8").casefold()
    assert "producer_approved" not in text
    assert '"reviewer":null' in text


def test_unsupported_staging_version_and_malformed_provenance_fail(tmp_path):
    future = staging_dict()
    future["schema_version"] = 99
    with pytest.raises(ValueError, match="version"):
        load_staging(json.dumps(future).encode())
    bad = staging_dict()
    bad["sources"][0]["url"] = None
    bad["sources"][0]["local_document_id"] = None
    roster, manifest, staging = write_inputs(tmp_path, staging=bad)
    with pytest.raises(ValueError):
        import_college_pilot(roster, manifest, staging, tmp_path / "out.json", tmp_path / "report.md")
