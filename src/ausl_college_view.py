"""Pure presentation and copy models for producer college rÃ©sumÃ©s."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from ausl_college import (
    CollegeEnvelope,
    CollegeResume,
    ResolutionState,
    SourceProvenance,
    StatRecord,
    StatRecordType,
    ValueState,
    assess_completeness,
    resolve_candidates,
)
from ausl_college_approval import ApprovedCollegeArtifact
from ausl_enrichment import EnrichmentMode


@dataclass(frozen=True)
class CollegeFieldView:
    field_id: str
    section: str
    scope_label: str
    display_text: str
    copy_text: str
    copy_with_source: str
    source_summary: str
    copy_eligible: bool
    block_reason: str
    candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollegeResumeView:
    available: bool
    player_id: str | None
    player_name: str
    current_team: str
    current_status: str
    message: str
    warning: str
    completeness: str
    missing_fields: tuple[str, ...]
    reviewed_date: str
    school_timeline: tuple[str, ...]
    stat_fields: tuple[CollegeFieldView, ...]
    batting_fields: tuple[CollegeFieldView, ...]
    pitching_fields: tuple[CollegeFieldView, ...]
    achievement_fields: tuple[CollegeFieldView, ...]
    source_summaries: tuple[str, ...]
    summary_copy_text: str
    summary_copy_with_source: str
    summary_copy_eligible: bool
    summary_block_reason: str


_METRIC_ORDER = {
    "batting_average": 10,
    "hits": 20,
    "home_runs": 30,
    "rbi": 40,
    "runs": 50,
    "era": 10,
    "wins": 20,
    "losses": 21,
    "innings_outs": 30,
    "pitching_strikeouts": 40,
    "strikeouts": 40,
    "whip": 50,
}

_COUNT_LABELS = {
    "games": "G",
    "at_bats": "AB",
    "plate_appearances": "PA",
    "runs": "R",
    "hits": "H",
    "doubles": "2B",
    "triples": "3B",
    "home_runs": "HR",
    "rbi": "RBI",
    "walks": "BB",
    "strikeouts": "SO",
    "stolen_bases": "SB",
    "earned_runs": "ER",
    "saves": "SV",
    "pitching_strikeouts": "SO",
}


def format_innings_outs(value) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Unavailable"
    try:
        outs = int(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if outs < 0:
        return "Unavailable"
    return f"{outs // 3}.{outs % 3} IP"


def _rate(value, places: int, *, leading_zero: bool = True) -> str:
    if value is None:
        return "Unavailable"
    decimal = Decimal(str(value)).quantize(
        Decimal("1." + "0" * places), rounding=ROUND_HALF_UP
    )
    text = format(decimal, f".{places}f")
    if not leading_zero and text.startswith("0."):
        text = text[1:]
    return text


def _format_metric(metric: str, value) -> str:
    if value is None:
        return "Unavailable"
    if metric in {"batting_average", "on_base_percentage", "slugging_percentage"}:
        return f"{_rate(value, 3, leading_zero=False)} { {'batting_average': 'AVG', 'on_base_percentage': 'OBP', 'slugging_percentage': 'SLG'}[metric] }"
    if metric in {"era", "whip"}:
        return f"{_rate(value, 2)} {metric.upper()}"
    if metric == "innings_outs":
        return format_innings_outs(value)
    if metric in _COUNT_LABELS:
        return f"{int(value)} {_COUNT_LABELS[metric]}"
    return f"{int(value) if isinstance(value, int) else value} {metric.replace('_', ' ').upper()}"


def _source_line(sources: Iterable[SourceProvenance], reviewed_date: str) -> str:
    ordered = sorted(sources, key=lambda source: source.source_id)
    labels = []
    for source in ordered:
        label = f"{source.organization}, {source.title}"
        if label not in labels:
            labels.append(label)
    return f"Source: {'; '.join(labels)}, reviewed {reviewed_date}"


def _record_program(resume: CollegeResume, record: StatRecord) -> str:
    programs = {program.program_id: program.display_name for program in resume.programs}
    if record.program_id:
        return programs.get(record.program_id, "Unavailable")
    return " / ".join(
        programs.get(stint.program_id, stint.program_id)
        for stint in sorted(resume.stints, key=lambda item: item.transfer_order)
    ) or "Unavailable"


def _record_scope(record: StatRecord, program: str) -> tuple[str, str]:
    if record.record_type in {
        StatRecordType.SOURCE_CAREER_BATTING,
        StatRecordType.SOURCE_CAREER_PITCHING,
        StatRecordType.DERIVED_CAREER_BATTING,
        StatRecordType.DERIVED_CAREER_PITCHING,
    }:
        return f"COLLEGE CAREER â€” {program.upper()}", f"COLLEGE CAREER ({program.upper()})"
    season = str(record.season) if record.season is not None else "UNKNOWN"
    return (
        f"{season} COLLEGE SEASON â€” {program.upper()}",
        f"{season} COLLEGE SEASON ({program.upper()})",
    )


def _stat_field(
    resume: CollegeResume,
    record: StatRecord,
    *,
    sources: dict[str, SourceProvenance],
    approved_candidate_ids: set[str],
    reviewed_date: str,
    copy_mode_allowed: bool,
) -> CollegeFieldView | None:
    resolved = []
    blocked = []
    used_sources = []
    for candidate in sorted(
        record.candidates,
        key=lambda item: (_METRIC_ORDER.get(item.metric_definition, 999), item.candidate_id),
    ):
        resolution = resolve_candidates((candidate,), sources)
        if resolution.state is not ResolutionState.RESOLVED or candidate.value_state is not ValueState.PRESENT:
            blocked.append("missing or conflicting college value")
            continue
        resolved.append((candidate.metric_definition, resolution.selected_value, candidate.candidate_id))
        used_sources.append(sources[candidate.source_id])
        if candidate.candidate_id not in approved_candidate_ids:
            blocked.append("approval manifest does not cover this exact field")
    if not resolved:
        return None
    # Combine W-L only after both exact candidates resolve within one record.
    metrics = {name: value for name, value, _candidate_id in resolved}
    parts = []
    consumed = set()
    for metric, value, _candidate_id in resolved:
        if metric in consumed:
            continue
        if metric == "wins" and "losses" in metrics:
            parts.append(f"{int(value)}â€“{int(metrics['losses'])} W-L")
            consumed.update({"wins", "losses"})
            continue
        if metric == "losses" and "wins" in metrics:
            continue
        parts.append(_format_metric(metric, value))
        consumed.add(metric)
    program = _record_program(resume, record)
    scope_label, copy_scope = _record_scope(record, program)
    display_text = " Â· ".join(parts)
    source_summary = _source_line(used_sources, reviewed_date)
    copy_text = f"{resume.canonical_display_name.upper()} â€” {copy_scope}: {', '.join(parts)}"
    reason = ""
    if not copy_mode_allowed:
        reason = "Developer review mode is not air ready."
    elif blocked:
        reason = "; ".join(sorted(set(blocked)))
    eligible = not reason
    return CollegeFieldView(
        field_id=record.record_id,
        section="pitching" if "pitching" in record.record_type.value else "batting",
        scope_label=scope_label,
        display_text=display_text,
        copy_text=copy_text,
        copy_with_source=f"{copy_text}\n{source_summary}",
        source_summary=source_summary,
        copy_eligible=eligible,
        block_reason=reason,
        candidate_ids=tuple(candidate_id for _name, _value, candidate_id in resolved),
    )


def _achievement_field(
    resume: CollegeResume,
    achievement,
    *,
    programs: dict[str, str],
    sources: dict[str, SourceProvenance],
    reviewed_date: str,
    copy_mode_allowed: bool,
) -> CollegeFieldView:
    program = programs.get(achievement.program_id, "College") if achievement.program_id else "College"
    season = f"{achievement.season_or_date} " if achievement.season_or_date else ""
    scope = f"{season}COLLEGE {achievement.achievement_type.value.replace('_', ' ').upper()} â€” {program.upper()}"
    used_sources = [sources[source_id] for source_id in achievement.provenance_ids if source_id in sources]
    source_summary = _source_line(used_sources, reviewed_date)
    copy_text = f"{resume.canonical_display_name.upper()} â€” {scope}: {achievement.normalized_label}"
    reason = "" if copy_mode_allowed and len(used_sources) == len(achievement.provenance_ids) else (
        "Developer review mode is not air ready." if not copy_mode_allowed else "Achievement provenance is unavailable."
    )
    return CollegeFieldView(
        field_id=achievement.achievement_id,
        section="achievement",
        scope_label=scope,
        display_text=achievement.normalized_label,
        copy_text=copy_text,
        copy_with_source=f"{copy_text}\n{source_summary}",
        source_summary=source_summary,
        copy_eligible=not reason,
        block_reason=reason,
    )


def build_college_resume_view(
    artifact_or_envelope: ApprovedCollegeArtifact | CollegeEnvelope,
    *,
    player_id: str,
    mode: EnrichmentMode | str,
    current_team: str = "",
    current_status: str = "",
) -> CollegeResumeView:
    selected_mode = mode if isinstance(mode, EnrichmentMode) else EnrichmentMode(mode)
    if isinstance(artifact_or_envelope, ApprovedCollegeArtifact):
        artifact = artifact_or_envelope
        envelope = artifact.envelope
        approved_ids = set(artifact.manifest.candidate_ids)
        reviewed_date = artifact.manifest.review_date
        approval_valid = True
    else:
        envelope = artifact_or_envelope
        approved_ids = set()
        reviewed_date = "Unreviewed"
        approval_valid = False
    identity = str(player_id).strip()
    matches = [resume for resume in envelope.resumes if resume.player_id == identity]
    warning = (
        "DEVELOPER REVIEW â€” NOT AIR READY"
        if selected_mode is EnrichmentMode.DEVELOPER_REVIEW
        else ""
    )
    if len(matches) != 1:
        return CollegeResumeView(
            False,
            identity or None,
            "",
            current_team,
            current_status,
            "College rÃ©sumÃ© unavailable for this player. The current reviewed pilot covers ten players; no college history has been inferred.",
            warning,
            "Unavailable",
            (),
            reviewed_date,
            (),
            (),
            (),
            (),
            (),
            (),
            "",
            "",
            False,
            "No exact approved college rÃ©sumÃ© is available.",
        )
    resume = matches[0]
    source_map = {source.source_id: source for source in envelope.sources}
    copy_mode_allowed = (
        selected_mode is EnrichmentMode.PRODUCER_APPROVED and approval_valid
    )
    stat_fields = tuple(
        item
        for record in resume.stat_records
        if (
            item := _stat_field(
                resume,
                record,
                sources=source_map,
                approved_candidate_ids=approved_ids,
                reviewed_date=reviewed_date,
                copy_mode_allowed=copy_mode_allowed,
            )
        )
        is not None
    )
    programs = {program.program_id: program.display_name for program in resume.programs}
    achievements = tuple(
        _achievement_field(
            resume,
            achievement,
            programs=programs,
            sources=source_map,
            reviewed_date=reviewed_date,
            copy_mode_allowed=copy_mode_allowed,
        )
        for achievement in resume.achievements
    )
    timeline = tuple(
        programs.get(stint.program_id, stint.program_id)
        for stint in sorted(resume.stints, key=lambda item: item.transfer_order)
    )
    assessment = assess_completeness(resume, envelope)
    used_source_ids = sorted(
        {
            source_id
            for field in (*stat_fields, *achievements)
            for source_id in (
                source.source_id
                for source in envelope.sources
                if source.title in field.source_summary
            )
        }
    )
    source_summaries = tuple(
        f"{source_map[source_id].organization} â€” {source_map[source_id].title} ({source_map[source_id].locator})"
        for source_id in used_source_ids
    )
    copyable = tuple(field for field in (*stat_fields, *achievements) if field.copy_eligible)
    summary_lines = [
        f"{resume.canonical_display_name.upper()} â€” COLLEGE RÃ‰SUMÃ‰",
        f"SCHOOLS: {' â†’ '.join(timeline) if timeline else 'Unavailable'}",
        *(f"{field.scope_label}: {field.display_text}" for field in copyable),
        f"COMPLETENESS: {assessment.state.value}",
    ]
    summary = "\n".join(summary_lines) if copyable else ""
    summary_sources = sorted({field.source_summary for field in copyable})
    summary_with_source = summary + (
        "\n" + "\n".join(summary_sources) if summary_sources else ""
    )
    summary_reason = "" if copyable else (
        "Developer review mode is not air ready."
        if selected_mode is EnrichmentMode.DEVELOPER_REVIEW
        else "No approved college fields are available to copy."
    )
    return CollegeResumeView(
        True,
        resume.player_id,
        resume.canonical_display_name,
        current_team,
        current_status,
        "Reviewed college rÃ©sumÃ© loaded.",
        warning,
        assessment.state.value,
        assessment.missing_fields,
        reviewed_date,
        timeline,
        stat_fields,
        tuple(field for field in stat_fields if field.section == "batting"),
        tuple(field for field in stat_fields if field.section == "pitching"),
        achievements,
        source_summaries,
        summary,
        summary_with_source,
        bool(copyable),
        summary_reason,
    )

