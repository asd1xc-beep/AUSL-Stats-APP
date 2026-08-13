"""Local, fail-closed loading boundary for college résumé data."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from ausl_college import CollegeEnvelope, load_envelope, validate_envelope
from ausl_college_approval import (
    APPROVAL_MANIFEST_NAME,
    APPROVED_ENVELOPE_NAME,
    ApprovedCollegeArtifact,
    validate_approved_payload,
)
from ausl_college_batch_approval import (
    AGGREGATE_MANIFEST_NAME,
    ApprovedAggregateArtifact,
    validate_aggregate_approval,
)
from ausl_college_connection_approval import (
    APPROVED_CONNECTION_ARTIFACT_NAME,
    CONNECTION_APPROVAL_MANIFEST_NAME,
    ApprovedConnectionArtifact,
    validate_connection_approval,
)
from ausl_enrichment import EnrichmentMode


CollegeDataMode = EnrichmentMode


@dataclass(frozen=True)
class CollegeLoadResult:
    mode: CollegeDataMode
    available: bool
    copy_allowed: bool
    envelope: CollegeEnvelope | None
    approval: ApprovedCollegeArtifact | ApprovedAggregateArtifact | None
    message: str
    warning: str = ""
    source_directory: Path | None = None
    connection_approval: ApprovedConnectionArtifact | None = None
    connection_source_directory: Path | None = None


class CollegeStore:
    """Load only the explicitly requested local trust tier.

    A failed producer reload retains an already validated in-memory artifact,
    but a cold start never falls back to developer-review data.
    """

    def __init__(
        self,
        *,
        approved_directories: tuple[Path | str, ...],
        developer_pilot_path: Path | str,
        approved_connection_directories: tuple[Path | str, ...] = (),
        event_logger: Callable[..., None] | None = None,
    ):
        self.approved_directories = tuple(Path(path) for path in approved_directories)
        self.developer_pilot_path = Path(developer_pilot_path)
        self.approved_connection_directories = tuple(
            Path(path) for path in approved_connection_directories
        )
        self._event_logger = event_logger
        self._last_good: CollegeLoadResult | None = None

    @classmethod
    def default(cls, *, event_logger: Callable[..., None] | None = None):
        root = Path(__file__).resolve().parents[1]
        return cls(
            approved_directories=(
                root / "data" / "college_approved_phase7e",
                root / "data" / "college_approved",
                root / "data" / "exports",
            ),
            developer_pilot_path=root / "data" / "college_pilot" / "pilot_envelope.json",
            approved_connection_directories=(
                root / "data" / "college_connections_approved",
                root / "data" / "exports",
            ),
            event_logger=event_logger,
        )

    def _log(self, event: str, **fields):
        if self._event_logger is not None:
            self._event_logger(event, **fields)

    @staticmethod
    def _mode(value: CollegeDataMode | str) -> CollegeDataMode:
        try:
            return value if isinstance(value, EnrichmentMode) else EnrichmentMode(value)
        except ValueError as exc:
            raise ValueError(f"unsupported college data mode: {value}") from exc

    def load(self, mode: CollegeDataMode | str) -> CollegeLoadResult:
        selected = self._mode(mode)
        if selected is EnrichmentMode.CORE_ONLY:
            return CollegeLoadResult(
                selected,
                False,
                False,
                None,
                None,
                "COLLEGE DATA: CORE ONLY — approved college résumés are unavailable.",
            )
        if selected is EnrichmentMode.DEVELOPER_REVIEW:
            try:
                envelope = load_envelope(self.developer_pilot_path.read_bytes())
                report = validate_envelope(envelope)
                if not report.valid:
                    raise ValueError("developer-review pilot failed schema validation")
            except (OSError, ValueError) as exc:
                self._log(
                    "college_data_load_failed",
                    mode=selected.value,
                    error_type=type(exc).__name__,
                )
                return CollegeLoadResult(
                    selected,
                    False,
                    False,
                    None,
                    None,
                    f"College developer-review data unavailable: {type(exc).__name__}.",
                    "DEVELOPER REVIEW — NOT AIR READY",
                )
            return CollegeLoadResult(
                selected,
                True,
                False,
                envelope,
                None,
                "Developer-review college pilot loaded for diagnostics.",
                "DEVELOPER REVIEW — NOT AIR READY",
                self.developer_pilot_path.parent,
            )

        error: Exception | None = None
        for directory in self.approved_directories:
            envelope_path = directory / APPROVED_ENVELOPE_NAME
            manifest_path = directory / APPROVAL_MANIFEST_NAME
            aggregate_manifest_path = directory / AGGREGATE_MANIFEST_NAME
            if (
                not envelope_path.is_file()
                and not manifest_path.is_file()
                and not aggregate_manifest_path.is_file()
            ):
                continue
            try:
                if aggregate_manifest_path.is_file():
                    artifact = validate_aggregate_approval(
                        envelope_path.read_bytes(),
                        aggregate_manifest_path.read_bytes(),
                    )
                else:
                    artifact = validate_approved_payload(
                        envelope_path.read_bytes(), manifest_path.read_bytes()
                    )
                connection_approval = None
                connection_directory = None
                for candidate_directory in self.approved_connection_directories:
                    candidate_path = (
                        candidate_directory / APPROVED_CONNECTION_ARTIFACT_NAME
                    )
                    approval_path = (
                        candidate_directory / CONNECTION_APPROVAL_MANIFEST_NAME
                    )
                    if not candidate_path.is_file() and not approval_path.is_file():
                        continue
                    connection_approval = validate_connection_approval(
                        candidate_path.read_bytes(), approval_path.read_bytes()
                    )
                    connection_directory = candidate_directory
                    break
            except (OSError, ValueError) as exc:
                error = exc
                break
            result = CollegeLoadResult(
                selected,
                True,
                True,
                artifact.envelope,
                artifact,
                "Producer-approved college résumés loaded and hash-validated.",
                "",
                directory,
                connection_approval,
                connection_directory,
            )
            self._last_good = result
            self._log(
                "college_data_load_succeeded",
                mode=selected.value,
                player_count=len(artifact.envelope.resumes),
            )
            return result

        if error is None:
            error = FileNotFoundError("matching college approval envelope and manifest are absent")
        self._log(
            "college_data_load_failed",
            mode=selected.value,
            error_type=type(error).__name__,
        )
        if self._last_good is not None:
            return replace(
                self._last_good,
                message="Approved college replacement failed validation; retained last-known-good snapshot.",
                warning=(
                    "COLLEGE DATA WARNING — invalid replacement rejected; "
                    "using last-known-good approved snapshot."
                ),
            )
        return CollegeLoadResult(
            selected,
            False,
            False,
            None,
            None,
            f"College approval unavailable or invalid: {type(error).__name__}.",
            "COLLEGE RÉSUMÉ UNAVAILABLE — approval validation failed closed.",
        )
