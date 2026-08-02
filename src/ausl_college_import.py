"""Explicit, offline, developer-review-only Phase 7C college pilot importer."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from ausl_college import (
    CORE_RESUME_V1,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    CollegeEnvelope,
    CompletenessState,
    IdentityReviewState,
    assess_completeness,
    load_envelope,
    serialize_envelope,
    validate_envelope,
)


MANIFEST_SCHEMA = "ausl-college-pilot-manifest"
STAGING_SCHEMA = "ausl-college-pilot-staging"
PILOT_SCHEMA_VERSION = 1
DEVELOPER_REVIEW_MODE = "developer_review"
MAX_INPUT_BYTES = 5_000_000
REQUIRED_COVERAGE = frozenset(
    {
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
    }
)


def _required(value: Any, label: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _strict(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{label} is missing fields: {sorted(missing)}")


def _json_bytes(payload: bytes, label: str) -> Any:
    if not isinstance(payload, bytes) or len(payload) > MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds the safe input limit")
    try:
        return json.loads(
            payload.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"nonfinite value: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc


@dataclass(frozen=True)
class PilotManifestEntry:
    player_id: str
    display_name: str
    team_code: str
    roster_status: str
    expected_college_role: str
    coverage_categories: tuple[str, ...]
    reason: str
    initial_identity_source_id: str
    expected_evidence_issue: str | None

    def __post_init__(self):
        for name in (
            "player_id",
            "display_name",
            "team_code",
            "roster_status",
            "expected_college_role",
            "reason",
            "initial_identity_source_id",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.expected_college_role not in {"hitter", "pitcher", "two_way"}:
            raise ValueError("expected_college_role is unsupported")
        categories = tuple(sorted({_required(item, "coverage category") for item in self.coverage_categories}))
        if not categories:
            raise ValueError("coverage_categories are required")
        object.__setattr__(self, "coverage_categories", categories)
        if self.expected_evidence_issue is not None:
            object.__setattr__(self, "expected_evidence_issue", _required(self.expected_evidence_issue, "expected_evidence_issue"))


@dataclass(frozen=True)
class PilotManifest:
    pilot_id: str
    entries: tuple[PilotManifestEntry, ...]


@dataclass(frozen=True)
class PilotManifestReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    accepted_player_ids: tuple[str, ...]
    coverage_categories: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PilotStaging:
    generated_at: str
    envelope: CollegeEnvelope


@dataclass(frozen=True)
class PilotImportResult:
    promoted: bool
    output_path: Path
    review_report_path: Path
    envelope_sha256: str
    review_report_sha256: str


def load_pilot_manifest(payload: bytes) -> PilotManifest:
    data = _json_bytes(payload, "pilot manifest")
    if not isinstance(data, dict):
        raise ValueError("pilot manifest root must be an object")
    _strict(data, {"schema_name", "schema_version", "pilot_id", "entries"}, "pilot manifest")
    if data["schema_name"] != MANIFEST_SCHEMA:
        raise ValueError("pilot manifest schema name is unsupported")
    if data["schema_version"] != PILOT_SCHEMA_VERSION:
        raise ValueError("pilot manifest schema version is unsupported")
    if not isinstance(data["entries"], list):
        raise ValueError("pilot manifest entries must be a list")
    expected = {
        "player_id", "display_name", "team_code", "roster_status",
        "expected_college_role", "coverage_categories", "reason",
        "initial_identity_source_id", "expected_evidence_issue",
    }
    entries = []
    for raw in data["entries"]:
        if not isinstance(raw, dict):
            raise ValueError("pilot manifest entry must be an object")
        _strict(raw, expected, "pilot manifest entry")
        entries.append(PilotManifestEntry(**{**raw, "coverage_categories": tuple(raw["coverage_categories"])}))
    return PilotManifest(_required(data["pilot_id"], "pilot_id"), tuple(entries))


def _identifier(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def validate_pilot_manifest(manifest: PilotManifest, roster: pd.DataFrame) -> PilotManifestReport:
    errors: list[str] = []
    warnings: list[str] = []
    if len(manifest.entries) != 10:
        errors.append("Pilot roster must contain exactly ten entries.")
    ids = [item.player_id for item in manifest.entries]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"Duplicate AUSL player IDs: {', '.join(duplicates)}")
    if not isinstance(roster, pd.DataFrame) or not {"player_id", "player_name"}.issubset(roster.columns):
        errors.append("Canonical roster is unavailable or malformed.")
        return PilotManifestReport(tuple(errors), tuple(warnings), tuple(ids), ())
    roster_ids = roster["player_id"].map(_identifier)
    accepted: list[str] = []
    for entry in manifest.entries:
        accepted.append(entry.player_id)
        matches = roster.loc[roster_ids.eq(entry.player_id)]
        if len(matches) != 1:
            errors.append(f"AUSL player ID {entry.player_id} resolves to {len(matches)} roster rows.")
            continue
        row = matches.iloc[0]
        if str(row.get("player_name", "")).strip().casefold() != entry.display_name.casefold():
            errors.append(f"AUSL player ID {entry.player_id} display name disagrees with the canonical roster; identity was not remapped.")
        for field, column in (("team_code", "team_code"), ("roster_status", "roster_status")):
            actual = str(row.get(column, "")).strip()
            expected = getattr(entry, field)
            if actual and actual.casefold() != expected.casefold():
                warnings.append(f"{entry.player_id} {field} changed: manifest={expected}; roster={actual}.")
    coverage = tuple(sorted({category for item in manifest.entries for category in item.coverage_categories}))
    missing = sorted(REQUIRED_COVERAGE - set(coverage))
    if missing:
        errors.append(f"Pilot coverage is missing required categories: {', '.join(missing)}")
    return PilotManifestReport(tuple(errors), tuple(warnings), tuple(accepted), coverage)


def _collect_ids(raw: Mapping[str, Any]) -> None:
    source_ids = [str(item.get("source_id", "")) for item in raw["sources"]]
    if any(count > 1 for count in Counter(source_ids).values()):
        raise ValueError("duplicate source_id in staging")
    resume_ids = [str(item.get("resume_id", "")) for item in raw["resumes"]]
    if any(count > 1 for count in Counter(resume_ids).values()):
        raise ValueError("duplicate resume_id in staging")
    candidate_ids = [
        str(candidate.get("candidate_id", ""))
        for resume in raw["resumes"]
        for record in resume.get("stat_records", [])
        for candidate in record.get("candidates", [])
    ]
    if any(count > 1 for count in Counter(candidate_ids).values()):
        raise ValueError("duplicate candidate_id in staging")


def load_staging(payload: bytes) -> PilotStaging:
    data = _json_bytes(payload, "pilot staging")
    if not isinstance(data, dict):
        raise ValueError("pilot staging root must be an object")
    expected = {"schema_name", "schema_version", "mode", "generated_at", "completeness_profile", "sources", "resumes", "validation_metadata"}
    _strict(data, expected, "pilot staging")
    if data["schema_name"] != STAGING_SCHEMA:
        raise ValueError("pilot staging schema name is unsupported")
    if data["schema_version"] != PILOT_SCHEMA_VERSION:
        raise ValueError("pilot staging schema version is unsupported")
    if data["mode"] != DEVELOPER_REVIEW_MODE:
        raise ValueError("pilot staging must explicitly use developer_review mode")
    if data["completeness_profile"] != CORE_RESUME_V1:
        raise ValueError("pilot staging completeness profile is unsupported")
    if not isinstance(data["sources"], list) or not isinstance(data["resumes"], list):
        raise ValueError("pilot staging sources and resumes must be lists")
    _collect_ids(data)
    for source in data["sources"]:
        if not source.get("url") and not source.get("local_document_id"):
            raise ValueError(f"source {source.get('source_id')} has no evidence reference")
    for resume in data["resumes"]:
        for record in resume.get("stat_records", []):
            for candidate in record.get("candidates", []):
                if "raw_source_value" not in candidate:
                    raise ValueError(
                        f"candidate {candidate.get('candidate_id')} is missing raw_source_value"
                    )
                raw = candidate.pop("raw_source_value")
                if isinstance(raw, (dict, list)):
                    raise ValueError(
                        f"candidate {candidate.get('candidate_id')} raw_source_value must be scalar"
                    )
    envelope_data = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": data["generated_at"],
        "completeness_profile": data["completeness_profile"],
        "sources": data["sources"],
        "resumes": data["resumes"],
        "validation_metadata": data["validation_metadata"],
    }
    envelope = load_envelope((json.dumps(envelope_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return PilotStaging(str(data["generated_at"]), envelope)


def build_envelope_from_staging(manifest: PilotManifest, staging: PilotStaging) -> CollegeEnvelope:
    expected = {item.player_id: item for item in manifest.entries}
    actual = {item.player_id: item for item in staging.envelope.resumes}
    if set(expected) != set(actual):
        raise ValueError("staging résumé IDs do not exactly match the pilot manifest")
    for player_id, entry in expected.items():
        resume = actual[player_id]
        if resume.canonical_display_name.casefold() != entry.display_name.casefold():
            raise ValueError(f"staging display name mismatch for AUSL player ID {player_id}")
        if not any(mapping.ausl_player_id == player_id and mapping.source_id == entry.initial_identity_source_id for mapping in resume.identity_mappings):
            raise ValueError(f"staging identity source mismatch for AUSL player ID {player_id}")
        if any(mapping.review_state is IdentityReviewState.AMBIGUOUS for mapping in resume.identity_mappings):
            raise ValueError(f"ambiguous identity mapping for AUSL player ID {player_id}")
    report = validate_envelope(staging.envelope)
    structural = tuple(error for error in report.errors if not error.startswith("unresolved identity:"))
    if structural:
        raise ValueError("Phase 7B envelope validation failed: " + "; ".join(structural))
    return staging.envelope


def _source_map(envelope: CollegeEnvelope):
    return {item.source_id: item for item in envelope.sources}


def render_review_packet(manifest: PilotManifest, envelope: CollegeEnvelope) -> str:
    sources = _source_map(envelope)
    by_player = {item.player_id: item for item in envelope.resumes}
    validation = validate_envelope(envelope)
    assessments = {player_id: assess_completeness(resume, envelope) for player_id, resume in by_player.items()}
    totals = Counter(item.state.value for item in assessments.values())
    source_types = Counter(item.source_type.value for item in envelope.sources)
    lines = [
        "# Phase 7C College Résumé Pilot Review Packet",
        "",
        "Status: **PRODUCER REVIEW PENDING**",
        "",
        "## Aggregate coverage summary",
        "",
        f"- Players: {len(manifest.entries)}",
        f"- Coverage: {', '.join(sorted({c for e in manifest.entries for c in e.coverage_categories}))}",
        f"- Verified: {totals.get('Verified', 0)}",
        f"- Partial: {totals.get('Partial', 0)}",
        f"- Needs Review: {totals.get('Needs Review', 0)}",
        f"- Unresolved identities: {len(validation.unresolved_identities)}",
        f"- Unresolved conflicts: {len(validation.unresolved_conflicts)}",
        f"- Missing provenance: {len(validation.missing_provenance)}",
        f"- Records rejected by validation: {len(validation.errors)}",
        "- Fields by source type: " + ", ".join(
            f"{name}={count}" for name, count in sorted(source_types.items())
        ),
        "- Source coverage gaps: human identity review for all pilot résumés; additional unavailable sections are listed per player.",
        "- Recommended résumé section order: Identity; Schools/Transfer Timeline; Career Totals; Final Season; Honors/Records; WCWS/Championships; Sources/Completeness.",
        "",
    ]
    for entry in sorted(manifest.entries, key=lambda item: (item.display_name.casefold(), item.player_id)):
        resume = by_player[entry.player_id]
        assessment = assessments[entry.player_id]
        lines.extend([
            f"## {entry.display_name} — AUSL ID {entry.player_id}", "",
            f"- AUSL context: {entry.team_code}; {entry.roster_status}",
            f"- Expected college role: {entry.expected_college_role}",
            f"- Completeness: **{assessment.state.value}**",
            f"- Missing expected fields: {', '.join(assessment.missing_fields) or 'None'}",
            f"- Blocking issues: {', '.join(assessment.blocking_reasons) or 'None'}",
            "- School/transfer timeline: " + "; ".join(
                f"{program.display_name} ({stint.start_season or '?'}–{stint.end_season or '?'})"
                for stint in sorted(resume.stints, key=lambda item: item.transfer_order)
                for program in resume.programs if program.program_id == stint.program_id
            ),
            "", "### Candidate facts for later review", "",
        ])
        for record in sorted(resume.stat_records, key=lambda item: item.record_id):
            for candidate in sorted(record.candidates, key=lambda item: item.candidate_id):
                value = "missing" if candidate.value is None else str(candidate.value)
                lines.append(f"- `{candidate.candidate_id}`: {candidate.metric_definition} = {value} ({record.record_type.value}, {record.role.value}); source `{candidate.source_id}`.")
        if not resume.stat_records:
            lines.append("- No statistical candidate is sufficiently normalized.")
        lines.extend(["", "### Source references", ""])
        referenced = sorted({resume.display_name_source_id, *(m.source_id for m in resume.identity_mappings), *(s for p in resume.programs for s in p.source_ids), *(c.source_id for r in resume.stat_records for c in r.candidates)})
        for source_id in referenced:
            source = sources[source_id]
            lines.append(f"- `{source_id}` — {source.organization}, *{source.title}*, {source.locator}; {source.url or source.local_document_id}.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_latest_roster(path: Path) -> pd.DataFrame:
    with pd.ExcelFile(path) as workbook:
        sheets = [
            name for name in workbook.sheet_names if name.startswith("roster_")
        ]
        if not sheets:
            raise ValueError("canonical roster workbook has no roster sheet")
        return pd.read_excel(workbook, sheet_name=sorted(sheets)[-1])


def _temporary(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="wb", prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False)
    path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _promote_pair(output: Path, output_bytes: bytes, report: Path, report_bytes: bytes, *, replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] = os.replace) -> None:
    old = {path: path.read_bytes() if path.exists() else None for path in (output, report)}
    staged = {output: _temporary(output, output_bytes), report: _temporary(report, report_bytes)}
    promoted: list[Path] = []
    try:
        for destination in (output, report):
            replace_func(staged[destination], destination)
            promoted.append(destination)
    except Exception:
        for destination in reversed(promoted):
            previous = old[destination]
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                restore = _temporary(destination, previous)
                os.replace(restore, destination)
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def import_college_pilot(roster_path: Path | str, manifest_path: Path | str, staging_path: Path | str, output_path: Path | str, review_report_path: Path | str, *, replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] = os.replace) -> PilotImportResult:
    import hashlib
    roster_path, manifest_path, staging_path, output_path, review_report_path = map(Path, (roster_path, manifest_path, staging_path, output_path, review_report_path))
    manifest = load_pilot_manifest(manifest_path.read_bytes())
    roster_report = validate_pilot_manifest(manifest, _read_latest_roster(roster_path))
    if not roster_report.valid:
        raise ValueError("Pilot roster validation failed: " + "; ".join(roster_report.errors))
    staging = load_staging(staging_path.read_bytes())
    envelope = build_envelope_from_staging(manifest, staging)
    output_bytes = serialize_envelope(envelope)
    report_bytes = render_review_packet(manifest, envelope).encode("utf-8")
    _promote_pair(output_path, output_bytes, review_report_path, report_bytes, replace_func=replace_func)
    return PilotImportResult(True, output_path, review_report_path, hashlib.sha256(output_bytes).hexdigest(), hashlib.sha256(report_bytes).hexdigest())
