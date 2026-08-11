# Phase 7C Ten-Player College Résumé Pilot Cohort

Status: **DEVELOPER REVIEW — PRODUCER REVIEW PENDING**

This pilot contains exactly ten current AUSL player IDs from the canonical
`roster_2026` sheet. Names are included for readability, but the importer
validates identity only by the stable AUSL ID and never falls back to a name.
The cohort is intentionally varied enough to exercise the accepted Phase 7B
envelope without beginning the Phase 7D College Résumé UI.

## Coverage matrix

| AUSL ID | Player | AUSL context | College role | Pilot coverage | Selection rationale |
|---|---|---|---|---|---|
| `950` | Valerie Cagle | CAR · Active | Two-way | veteran; single school; two-way; award/record | Clemson provides authoritative career batting and pitching tables. |
| `278` | Rachel Garcia | TEX · Active | Two-way | veteran; single school; two-way; award/record; championship | UCLA supplies separate 2021 batting and pitching evidence plus championship context. |
| `1327` | NiJaree Canady | TEX · Active | Two-way | early career; transfer; pitcher/two-way; award; WCWS | Stanford-to-Texas Tech history exercises a recent transfer and separate-role evidence. |
| `1075` | Tiare Jennings | TEX · Active | Hitter | veteran; single school; hitter; record; championship | Oklahoma publishes an official AUSL-season profile with her career totals and four championships. |
| `1324` | Karlyn Pickens | CAR · Active | Pitcher | early career; single school; pitcher; award; WCWS | Tennessee provides a recent official pitching season and national award context. |
| `169` | Odicci Alexander-Bennett | CHI · Active | Two-way | veteran; single school; two-way; WCWS | James Madison supplies separate 2021 batting/pitching evidence and WCWS context. |
| `1285` | Kelly Maxwell | PDX · Active | Pitcher | transfer; pitcher; award; championship | Oklahoma State-to-Oklahoma history exercises multi-school and championship coverage. |
| `1102` | Korbe Otis | PDX · Active | Hitter | transfer; hitter; award; WCWS | Louisville-to-Florida history provides a multi-school hitter and recent final season. |
| `1322` | Ailana Agbayani | CHI · Active | Two-way | early career; transfer; hitter/pitcher; deliberately incomplete | BYU-to-Oklahoma evidence preserves incomplete pitching-career scope instead of inferring totals. |
| `933` | Kayla Kowalik | CAR · Injured — Temporary | Hitter | single school; hitter; award/record | Kentucky provides a high-value final-college-season and program-record case. |

All required cohort categories are represented: early-career, AUSL veteran,
single-school, multi-school, hitter, pitcher, two-way, award/record,
WCWS/championship, and deliberately incomplete/conflicting evidence.

## Source plan and identity boundary

- The canonical AUSL roster export supplies the initial exact-ID crosswalk.
- Official school athletics biographies, statistics tables, and record pages
  supply the normalized college evidence in this pilot.
- Each school, stint, statistic candidate, and achievement retains its own
  source ID and locator in the accepted Phase 7B envelope.
- Identity mappings remain `needs_review`; no automated action fabricates a
  reviewer, approval timestamp, producer sign-off, or air-ready status.
- Full source references and every candidate value appear in
  `Phase_7C_Review_Packet.md`.

## Known difficult cases

- Ailana Agbayani has source-backed BYU season pitching values but no selected
  reconciled college-career pitching total. That omission is explicit.
- Two-way batting and pitching records are normalized independently.
- Career records reported by a source remain distinct from season records;
  the pilot does not derive a career total from incomplete season coverage.
- An explicit source value of zero would remain zero, while missing and
  unavailable values remain null states. No pilot field is filled for visual
  symmetry.

## Exact scope

The pilot consists of the manifest, normalized review staging, accepted Phase
7B envelope, deterministic review packet, explicit offline importer, and
validation tests. It is excluded from core and approved-enrichment producer
distributions. Ordinary startup, Local/Offline Mode, Full Enrichment Refresh,
facts, comparison, copy, pin, rundown, packets, and What Changed do not load or
rewrite it. Phase 7D remains not started.
