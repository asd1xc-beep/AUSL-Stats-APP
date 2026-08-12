"""Phase 7E full-roster coverage and bounded developer-review batches.

This module is GUI-free and network-free.  It accounts for exact canonical
AUSL roster identities, preserves the accepted Phase 7B envelope, and emits
review-only batches.  It never creates producer approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from ausl_college import (
    CORE_RESUME_V1,
    CollegeEnvelope,
    CollegeResume,
    CompletenessState,
    IdentityMapping,
    IdentityReviewState,
    Program,
    ProgramStint,
    SourceProvenance,
    SourceType,
    assess_completeness,
    serialize_envelope,
    validate_envelope,
)
from ausl_college_approval import ApprovedCollegeArtifact


COVERAGE_SCHEMA_NAME = "ausl-college-roster-coverage"
COVERAGE_SCHEMA_VERSION = 1
BATCH_SCHEMA_NAME = "ausl-college-review-batch"
BATCH_SCHEMA_VERSION = 1
MIN_BATCH_SIZE = 8
MAX_BATCH_SIZE = 12
DEFAULT_BATCH_SIZE = 10


class CoverageState(str, Enum):
    APPROVED_RESUME_AVAILABLE = "approved_resume_available"
    REVIEWED_PARTIAL_RESUME = "reviewed_partial_resume"
    DEVELOPER_REVIEW_PENDING = "developer_review_pending"
    EXACT_IDENTITY_UNRESOLVED = "exact_identity_unresolved"
    OFFICIAL_SOURCE_UNAVAILABLE = "official_source_unavailable"
    NO_SAFE_RESUME_AVAILABLE = "no_safe_resume_available"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _identifier(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _id_sort(value: str):
    return (0, int(value)) if value.isdigit() else (1, value.casefold(), value)


@dataclass(frozen=True)
class RosterCoverageEntry:
    player_id: str
    display_name: str
    team_code: str | None
    roster_status: str
    coverage_state: CoverageState
    college_resume_id: str | None
    batch_id: str
    identity_review_status: str
    completeness_status: str
    unresolved_reason: str | None


@dataclass(frozen=True)
class RosterCoverageManifest:
    manifest_id: str
    season: int
    generated_at: datetime
    batch_size: int
    entries: tuple[RosterCoverageEntry, ...]
    schema_name: str = COVERAGE_SCHEMA_NAME
    schema_version: int = COVERAGE_SCHEMA_VERSION

    @property
    def coverage_totals(self) -> dict[str, int]:
        counts = Counter(entry.coverage_state.value for entry in self.entries)
        return {state.value: counts[state.value] for state in CoverageState}


@dataclass(frozen=True)
class CoverageValidationReport:
    errors: tuple[str, ...]
    missing_player_ids: tuple[str, ...]
    extra_player_ids: tuple[str, ...]
    name_disagreements: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class BatchPlayer:
    player_id: str
    display_name: str


@dataclass(frozen=True)
class CollegeBatchManifest:
    batch_id: str
    coverage_manifest_id: str
    season: int
    generated_at: datetime
    players: tuple[BatchPlayer, ...]
    schema_name: str = BATCH_SCHEMA_NAME
    schema_version: int = BATCH_SCHEMA_VERSION

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(player.player_id for player in self.players)


def _roster_for_season(roster: pd.DataFrame, season: int) -> pd.DataFrame:
    required = {
        "season",
        "player_id",
        "player_name",
        "team_code",
        "roster_status",
        "position",
        "college",
    }
    if not isinstance(roster, pd.DataFrame) or not required.issubset(roster.columns):
        raise ValueError("canonical roster is unavailable or malformed")
    season_values = pd.to_numeric(roster["season"], errors="coerce")
    frame = roster.loc[season_values.eq(season)].copy()
    if frame.empty:
        raise ValueError(f"canonical roster has no rows for season {season}")
    frame["_player_id"] = frame["player_id"].map(_identifier)
    if frame["_player_id"].eq("").any():
        raise ValueError("canonical roster contains a missing AUSL player ID")
    duplicates = sorted(
        (player_id for player_id, count in Counter(frame["_player_id"]).items() if count > 1),
        key=_id_sort,
    )
    if duplicates:
        raise ValueError("duplicate AUSL player ID: " + ", ".join(duplicates))
    if frame["player_name"].map(_text).eq("").any():
        raise ValueError("canonical roster contains a missing display name")
    return frame


def build_roster_coverage(
    roster: pd.DataFrame,
    *,
    season: int,
    generated_at: datetime,
    approved_artifact: ApprovedCollegeArtifact | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RosterCoverageManifest:
    if isinstance(season, bool) or not isinstance(season, int) or season < 2000:
        raise ValueError("season must be an exact configured season")
    if batch_size < MIN_BATCH_SIZE or batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}")
    frame = _roster_for_season(roster, season)
    approved: dict[str, tuple[CollegeResume, CompletenessState]] = {}
    if approved_artifact is not None:
        for resume in approved_artifact.envelope.resumes:
            approved[resume.player_id] = (
                resume,
                assess_completeness(resume, approved_artifact.envelope).state,
            )

    pending_rows: list[tuple[str, pd.Series]] = []
    prepared: dict[str, dict[str, object]] = {}
    for _, row in frame.iterrows():
        player_id = row["_player_id"]
        display_name = _text(row["player_name"])
        reviewed = approved.get(player_id)
        if reviewed is not None and reviewed[0].canonical_display_name.casefold() != display_name.casefold():
            prepared[player_id] = {
                "state": CoverageState.EXACT_IDENTITY_UNRESOLVED,
                "resume_id": None,
                "identity": "name_disagreement",
                "completeness": "Needs Review",
                "reason": "Approved résumé display name disagrees with the canonical roster; identity was not remapped.",
            }
        elif reviewed is not None:
            resume, completeness = reviewed
            state = (
                CoverageState.APPROVED_RESUME_AVAILABLE
                if completeness is CompletenessState.VERIFIED
                else CoverageState.REVIEWED_PARTIAL_RESUME
            )
            prepared[player_id] = {
                "state": state,
                "resume_id": resume.resume_id,
                "identity": "approved_exact_id",
                "completeness": completeness.value,
                "reason": None,
            }
        elif not _text(row["college"]):
            prepared[player_id] = {
                "state": CoverageState.OFFICIAL_SOURCE_UNAVAILABLE,
                "resume_id": None,
                "identity": "exact_id_only",
                "completeness": "Needs Review",
                "reason": "Canonical AUSL roster has no college program value; no résumé was manufactured.",
            }
            pending_rows.append((player_id, row))
        else:
            prepared[player_id] = {
                "state": CoverageState.DEVELOPER_REVIEW_PENDING,
                "resume_id": None,
                "identity": "exact_id_review_pending",
                "completeness": "Needs Review",
                "reason": "Only the canonical AUSL roster school value is available; cross-source identity and résumé review are pending.",
            }
            pending_rows.append((player_id, row))

    pending_ids = sorted((player_id for player_id, _ in pending_rows), key=_id_sort)
    pending_batch = {
        player_id: f"phase7e-{season}-batch-{index // batch_size + 1:02d}"
        for index, player_id in enumerate(pending_ids)
    }
    entries = []
    for _, row in sorted(frame.iterrows(), key=lambda item: _id_sort(item[1]["_player_id"])):
        player_id = row["_player_id"]
        values = prepared[player_id]
        entries.append(
            RosterCoverageEntry(
                player_id=player_id,
                display_name=_text(row["player_name"]),
                team_code=_text(row["team_code"]) or None,
                roster_status=_text(row["roster_status"]) or "Unknown",
                coverage_state=values["state"],
                college_resume_id=values["resume_id"],
                batch_id=pending_batch.get(player_id, "phase7d-approved-pilot"),
                identity_review_status=str(values["identity"]),
                completeness_status=str(values["completeness"]),
                unresolved_reason=values["reason"],
            )
        )
    return RosterCoverageManifest(
        manifest_id=f"phase7e-roster-coverage-{season}-v1",
        season=season,
        generated_at=_utc(generated_at),
        batch_size=batch_size,
        entries=tuple(entries),
    )


def _coverage_mapping(manifest: RosterCoverageManifest) -> dict[str, object]:
    return {
        "schema_name": manifest.schema_name,
        "schema_version": manifest.schema_version,
        "manifest_id": manifest.manifest_id,
        "season": manifest.season,
        "generated_at": manifest.generated_at.isoformat(),
        "batch_size": manifest.batch_size,
        "coverage_totals": manifest.coverage_totals,
        "entries": [
            {
                "player_id": entry.player_id,
                "display_name": entry.display_name,
                "team_code": entry.team_code,
                "roster_status": entry.roster_status,
                "coverage_state": entry.coverage_state.value,
                "college_resume_id": entry.college_resume_id,
                "batch_id": entry.batch_id,
                "identity_review_status": entry.identity_review_status,
                "completeness_status": entry.completeness_status,
                "unresolved_reason": entry.unresolved_reason,
            }
            for entry in manifest.entries
        ],
    }


def serialize_coverage_manifest(manifest: RosterCoverageManifest) -> bytes:
    return (json.dumps(_coverage_mapping(manifest), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def load_coverage_manifest(payload: bytes) -> RosterCoverageManifest:
    if len(payload) > 5_000_000:
        raise ValueError("coverage manifest exceeds the safe size limit")
    raw = json.loads(payload.decode("utf-8"))
    expected = {
        "schema_name", "schema_version", "manifest_id", "season",
        "generated_at", "batch_size", "coverage_totals", "entries",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError("coverage manifest fields are missing or unknown")
    if raw["schema_name"] != COVERAGE_SCHEMA_NAME or raw["schema_version"] != COVERAGE_SCHEMA_VERSION:
        raise ValueError("coverage manifest schema is unsupported")
    entry_fields = {
        "player_id", "display_name", "team_code", "roster_status",
        "coverage_state", "college_resume_id", "batch_id",
        "identity_review_status", "completeness_status", "unresolved_reason",
    }
    entries = []
    for item in raw["entries"]:
        if not isinstance(item, dict) or set(item) != entry_fields:
            raise ValueError("coverage entry fields are missing or unknown")
        entries.append(
            RosterCoverageEntry(
                **{**item, "coverage_state": CoverageState(item["coverage_state"])}
            )
        )
    manifest = RosterCoverageManifest(
        manifest_id=str(raw["manifest_id"]),
        season=int(raw["season"]),
        generated_at=datetime.fromisoformat(raw["generated_at"]),
        batch_size=int(raw["batch_size"]),
        entries=tuple(entries),
    )
    if manifest.coverage_totals != raw["coverage_totals"]:
        raise ValueError("coverage totals do not match entries")
    return manifest


def validate_roster_coverage(
    manifest: RosterCoverageManifest,
    roster: pd.DataFrame,
    *,
    season: int,
) -> CoverageValidationReport:
    frame = _roster_for_season(roster, season)
    roster_by_id = {row["_player_id"]: row for _, row in frame.iterrows()}
    manifest_ids = [entry.player_id for entry in manifest.entries]
    duplicate_ids = sorted(
        (player_id for player_id, count in Counter(manifest_ids).items() if count > 1),
        key=_id_sort,
    )
    roster_ids = set(roster_by_id)
    coverage_ids = set(manifest_ids)
    missing = tuple(sorted(roster_ids - coverage_ids, key=_id_sort))
    extra = tuple(sorted(coverage_ids - roster_ids, key=_id_sort))
    disagreements = tuple(
        sorted(
            (
                entry.player_id
                for entry in manifest.entries
                if entry.player_id in roster_by_id
                and entry.display_name.casefold()
                != _text(roster_by_id[entry.player_id]["player_name"]).casefold()
            ),
            key=_id_sort,
        )
    )
    errors = []
    if manifest.season != season:
        errors.append("coverage season does not match canonical roster season")
    if duplicate_ids:
        errors.append("coverage contains duplicate exact AUSL player IDs")
    if missing:
        errors.append("current roster players are missing from coverage")
    if extra:
        errors.append("coverage contains players outside the current roster")
    if disagreements:
        errors.append("coverage display names disagree with exact roster IDs; identity was not remapped")
    return CoverageValidationReport(tuple(errors), missing, extra, disagreements)


def build_batch_manifests(manifest: RosterCoverageManifest) -> tuple[CollegeBatchManifest, ...]:
    grouped: dict[str, list[RosterCoverageEntry]] = {}
    for entry in manifest.entries:
        if entry.batch_id == "phase7d-approved-pilot":
            continue
        grouped.setdefault(entry.batch_id, []).append(entry)
    batches = []
    for batch_id in sorted(grouped):
        entries = sorted(grouped[batch_id], key=lambda item: _id_sort(item.player_id))
        if len(entries) > MAX_BATCH_SIZE:
            raise ValueError(f"batch {batch_id} exceeds the safe player limit")
        batches.append(
            CollegeBatchManifest(
                batch_id=batch_id,
                coverage_manifest_id=manifest.manifest_id,
                season=manifest.season,
                generated_at=manifest.generated_at,
                players=tuple(BatchPlayer(item.player_id, item.display_name) for item in entries),
            )
        )
    return tuple(batches)


def render_roster_coverage_report(manifest: RosterCoverageManifest) -> str:
    totals = manifest.coverage_totals
    batches = build_batch_manifests(manifest)
    unresolved = tuple(
        entry
        for entry in manifest.entries
        if entry.coverage_state
        not in {
            CoverageState.APPROVED_RESUME_AVAILABLE,
            CoverageState.REVIEWED_PARTIAL_RESUME,
        }
    )
    lines = [
        "# Phase 7E Current-Roster College Coverage Report",
        "",
        "Status: **FULL-ROSTER COLLEGE IMPORT COMPLETE — BATCH REVIEW PENDING**",
        "",
        f"- Season: {manifest.season}",
        f"- Coverage manifest: `{manifest.manifest_id}`",
        f"- Exact roster IDs accounted for: {len(manifest.entries)}",
        f"- Approved résumés available: {totals[CoverageState.APPROVED_RESUME_AVAILABLE.value]}",
        f"- Reviewed Partial résumés: {totals[CoverageState.REVIEWED_PARTIAL_RESUME.value]}",
        f"- Developer review pending: {totals[CoverageState.DEVELOPER_REVIEW_PENDING.value]}",
        f"- Exact identity unresolved: {totals[CoverageState.EXACT_IDENTITY_UNRESOLVED.value]}",
        f"- Official source unavailable: {totals[CoverageState.OFFICIAL_SOURCE_UNAVAILABLE.value]}",
        f"- No safe résumé available: {totals[CoverageState.NO_SAFE_RESUME_AVAILABLE.value]}",
        f"- Review batches: {len(batches)}",
        "- Source scope for new batches: canonical official AUSL roster identity and compact school field only",
        "- Producer approval for new batches: absent",
        "",
        "## Batch matrix",
        "",
        "| Batch | Players | Exact AUSL IDs | Review state |",
        "|---|---:|---|---|",
    ]
    for batch in batches:
        lines.append(
            f"| `{batch.batch_id}` | {len(batch.player_ids)} | "
            f"{', '.join(batch.player_ids)} | Pending |"
        )
    lines.extend(
        [
            "",
            "## Unresolved and pending coverage",
            "",
            "Every row below remains excluded from producer-approved college data until its exact batch is reviewed and separately approved.",
            "",
            "| AUSL ID | Player | Team/status | Batch | State | Reason |",
            "|---|---|---|---|---|---|",
        ]
    )
    for entry in sorted(unresolved, key=lambda item: _id_sort(item.player_id)):
        team = entry.team_code or "No current team"
        reason = (entry.unresolved_reason or "Review pending").replace("|", "/")
        lines.append(
            f"| {entry.player_id} | {entry.display_name} | {team}; {entry.roster_status} | "
            f"`{entry.batch_id}` | {entry.coverage_state.value} | {reason} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _batch_mapping(batch: CollegeBatchManifest) -> dict[str, object]:
    return {
        "schema_name": batch.schema_name,
        "schema_version": batch.schema_version,
        "batch_id": batch.batch_id,
        "coverage_manifest_id": batch.coverage_manifest_id,
        "season": batch.season,
        "generated_at": batch.generated_at.isoformat(),
        "mode": "developer_review",
        "players": [
            {"player_id": item.player_id, "display_name": item.display_name}
            for item in batch.players
        ],
    }


def serialize_batch_manifest(batch: CollegeBatchManifest) -> bytes:
    return (json.dumps(_batch_mapping(batch), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _program_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return f"review-program-{slug or 'unresolved'}"


def build_developer_review_batch(
    batch: CollegeBatchManifest,
    roster: pd.DataFrame,
    *,
    generated_at: datetime,
    roster_snapshot_hash: str,
    source_url: str,
) -> CollegeEnvelope:
    if not re.fullmatch(r"[0-9a-f]{64}", roster_snapshot_hash):
        raise ValueError("roster_snapshot_hash must be a SHA-256 digest")
    if not source_url.startswith("https://"):
        raise ValueError("official roster source URL must use HTTPS")
    frame = _roster_for_season(roster, batch.season)
    by_id = {row["_player_id"]: row for _, row in frame.iterrows()}
    sources = []
    resumes = []
    for player in batch.players:
        row = by_id.get(player.player_id)
        if row is None:
            raise ValueError(f"AUSL player ID {player.player_id} does not resolve to exactly one canonical roster row")
        canonical_name = _text(row["player_name"])
        if canonical_name.casefold() != player.display_name.casefold():
            raise ValueError(f"canonical name disagreement for AUSL player ID {player.player_id}; identity was not remapped")
        source_id = f"ausl-roster-{batch.season}-{player.player_id}"
        sources.append(
            SourceProvenance(
                source_id=source_id,
                source_type=SourceType.OFFICIAL_AUSL_PROFILE,
                organization="Athletes Unlimited Softball League",
                title=f"{batch.season} canonical AUSL roster record — {canonical_name}",
                locator=f"roster_{batch.season}; player_id={player.player_id}",
                retrieved_at=_utc(generated_at),
                version=f"phase7e-roster-seed-v1:{roster_snapshot_hash}",
                verification_state="verified",
                url=source_url,
                local_document_id=f"ausl_rosters.xlsx:{roster_snapshot_hash}",
                content_hash=roster_snapshot_hash,
                review_note="Official AUSL roster record; cross-source college identity review remains pending.",
            )
        )
        college = _text(row["college"])
        programs = ()
        stints = ()
        program_status = "unavailable"
        if college:
            program_id = _program_id(college)
            programs = (
                Program(
                    program_id=program_id,
                    display_name=college,
                    source_ids=(source_id,),
                    source_identifiers=((source_id, college),),
                ),
            )
            stints = (
                ProgramStint(
                    stint_id=f"review-stint-{player.player_id}-1",
                    program_id=program_id,
                    transfer_order=1,
                    start_season=None,
                    end_season=None,
                    provenance_ids=(source_id,),
                    uncertainty_note="Canonical AUSL roster lists the program but does not provide attendance seasons.",
                ),
            )
            program_status = "needs_review"
        resumes.append(
            CollegeResume(
                resume_id=f"phase7e-review-resume-{player.player_id}",
                player_id=player.player_id,
                canonical_display_name=canonical_name,
                display_name_source_id=source_id,
                identity_mappings=(
                    IdentityMapping(
                        mapping_id=f"phase7e-review-identity-{player.player_id}",
                        ausl_player_id=player.player_id,
                        source_id=source_id,
                        source_athlete_id=f"ausl-roster-{player.player_id}",
                        aliases=(),
                        review_state=IdentityReviewState.NEEDS_REVIEW,
                        evidence_reference="Exact canonical AUSL roster ID; independent college identity review pending.",
                    ),
                ),
                programs=programs,
                stints=stints,
                stat_records=(),
                achievements=(),
                section_statuses=(
                    ("identity", "needs_review"),
                    ("programs", program_status),
                    ("statistics", "unavailable"),
                    ("achievements", "unavailable"),
                ),
            )
        )
    envelope = CollegeEnvelope(
        generated_at=_utc(generated_at),
        completeness_profile=CORE_RESUME_V1,
        resumes=tuple(resumes),
        sources=tuple(sources),
        validation_metadata=(
            ("mode", "developer_review"),
            ("batch_id", batch.batch_id),
            ("coverage_manifest_id", batch.coverage_manifest_id),
            ("producer_approval", "absent"),
            ("source_scope", "canonical AUSL roster compact resume only"),
        ),
    )
    report = validate_envelope(envelope)
    structural = tuple(
        error for error in report.errors if not error.startswith("unresolved identity:")
    )
    if structural:
        raise ValueError("Phase 7B envelope validation failed: " + "; ".join(structural))
    return envelope


def render_batch_review_packet(
    batch: CollegeBatchManifest,
    envelope: CollegeEnvelope,
) -> str:
    by_id = {resume.player_id: resume for resume in envelope.resumes}
    sources = {source.source_id: source for source in envelope.sources}
    lines = [
        f"# Phase 7E College Review Batch {batch.batch_id}",
        "",
        "Status: **BATCH REVIEW PENDING**",
        "",
        f"- Season: {batch.season}",
        f"- Exact AUSL IDs: {', '.join(batch.player_ids)}",
        f"- Player count: {len(batch.player_ids)}",
        "- Producer approval: absent",
        "- Evidence scope: canonical AUSL roster identity and compact school field only",
        "",
    ]
    for player in sorted(batch.players, key=lambda item: (item.display_name.casefold(), _id_sort(item.player_id))):
        resume = by_id[player.player_id]
        assessment = assess_completeness(resume, envelope)
        source_id = resume.display_name_source_id
        source = sources[source_id]
        schools = ", ".join(program.display_name for program in resume.programs) or "Unavailable"
        lines.extend(
            [
                f"## {player.display_name} — AUSL ID {player.player_id}",
                "",
                f"- Completeness: **{assessment.state.value}**",
                f"- School/program candidate: {schools}",
                "- Attendance seasons: Unavailable from this source",
                "- Statistics: Unavailable from this source",
                "- Achievements/WCWS/championships: Unavailable from this source",
                f"- Blocking issues: {', '.join(assessment.blocking_reasons) or 'None'}",
                f"- Missing fields: {', '.join(assessment.missing_fields) or 'None'}",
                f"- Source: {source.organization}, {source.title}",
                f"- Locator: {source.locator}",
                f"- Reference: {source.url or source.local_document_id}",
                "- Reviewer decision: PENDING",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def promote_batch_bundle(
    destination: Path | str,
    *,
    manifest_bytes: bytes,
    envelope_bytes: bytes,
    report_bytes: bytes,
    replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] = os.replace,
) -> Mapping[str, str]:
    destination = Path(destination)
    payloads = {
        "batch_manifest.json": manifest_bytes,
        "developer_review_envelope.json": envelope_bytes,
        "review_packet.md": report_bytes,
    }
    hashes = {name: _sha(payload) for name, payload in payloads.items()}
    if destination.is_dir() and all(
        (destination / name).is_file()
        and (destination / name).read_bytes() == payload
        for name, payload in payloads.items()
    ):
        return hashes
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent))
    backup: Path | None = None
    try:
        for name, payload in payloads.items():
            path = stage / name
            with path.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".backup", dir=destination.parent))
            backup.rmdir()
            os.replace(destination, backup)
        try:
            replace_func(stage, destination)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
        return hashes
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def batch_bundle_payloads(
    batch: CollegeBatchManifest,
    envelope: CollegeEnvelope,
) -> tuple[bytes, bytes, bytes]:
    return (
        serialize_batch_manifest(batch),
        serialize_envelope(envelope),
        render_batch_review_packet(batch, envelope).encode("utf-8"),
    )
