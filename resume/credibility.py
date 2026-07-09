import re
from dataclasses import dataclass, field
from datetime import date

from db.connection import get_conn
from resume.parser import ParsedResume

# Zone 4 ("considerable preparation" — bachelor's + several years) is used as the
# default baseline for a generic "senior"-type title when we can't map the resume's
# job title to a specific O*NET occupation code — see scripts/build_reference_stats.py
# for how these zone thresholds were derived from O*NET's own reference text.
DEFAULT_SENIOR_ZONE = 4

SENIOR_TITLE_KEYWORDS = ("senior", "staff", "principal", "lead", "director", "head of", "vp", "chief")

BUZZWORDS = (
    "results-driven", "team player", "synergy", "detail-oriented", "self-starter",
    "go-getter", "hard worker", "passionate", "dynamic", "proactive",
    "excellent communication skills", "think outside the box", "fast-paced environment",
    "wear many hats", "hit the ground running",
)
METRIC_PATTERN = re.compile(
    r"\$\s*\d+(\.\d+)?|\d+(\.\d+)?\s*(%|percent|x\b|million|billion|thousand|\bk\b|\$)", re.IGNORECASE
)
GAP_MONTHS_THRESHOLD = 3


@dataclass
class ConsistencyFlag:
    kind: str
    detail: str
    severity: str  # "low", "medium", "high"


@dataclass
class ConsistencyResult:
    flags: list[ConsistencyFlag] = field(default_factory=list)
    total_experience_years: float = 0.0


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _senior_min_years() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT min_years_estimate FROM onet_job_zones WHERE zone = ?", (DEFAULT_SENIOR_ZONE,)
        ).fetchone()
    return row["min_years_estimate"] if row else 4.0


def check_internal_consistency(parsed: ParsedResume, today: date | None = None) -> ConsistencyResult:
    """Pure Python/date-math checks — no LLM call. Flags timeline inconsistencies,
    seniority-vs-experience mismatches, buzzword-heavy/metric-light writing, and skill
    claims with no supporting evidence anywhere in the resume's own bullets."""
    today = today or date.today()
    flags: list[ConsistencyFlag] = []

    entries = sorted((e for e in parsed.experience if e.start_date is not None), key=lambda e: e.start_date)

    for prev, curr in zip(entries, entries[1:]):
        prev_end = prev.end_date or today
        if curr.start_date < prev_end:
            overlap_months = _months_between(curr.start_date, prev_end)
            flags.append(
                ConsistencyFlag(
                    kind="timeline_overlap",
                    detail=f'"{prev.title}" at {prev.company} overlaps with "{curr.title}" at {curr.company} by ~{overlap_months} month(s)',
                    severity="medium",
                )
            )
        else:
            gap_months = _months_between(prev_end, curr.start_date)
            if gap_months > GAP_MONTHS_THRESHOLD:
                flags.append(
                    ConsistencyFlag(
                        kind="timeline_gap",
                        detail=f'{gap_months}-month gap between "{prev.title}" at {prev.company} and "{curr.title}" at {curr.company}',
                        severity="low",
                    )
                )

    # Merge overlapping/adjacent date ranges before summing so concurrent roles
    # (e.g. a full-time job + a side/consulting gig at the same time) aren't
    # double-counted toward total experience.
    total_months = 0
    merged_start: date | None = None
    merged_end: date | None = None
    for entry in entries:
        entry_end = entry.end_date or today
        if merged_start is None:
            merged_start, merged_end = entry.start_date, entry_end
        elif entry.start_date <= merged_end:
            merged_end = max(merged_end, entry_end)
        else:
            total_months += max(0, _months_between(merged_start, merged_end))
            merged_start, merged_end = entry.start_date, entry_end
    if merged_start is not None:
        total_months += max(0, _months_between(merged_start, merged_end))
    total_years = round(total_months / 12, 1)

    senior_min_years = _senior_min_years()
    for i, entry in enumerate(entries):
        prior_months = 0
        for prior in entries[:i]:
            prior_end = min(prior.end_date or entry.start_date, entry.start_date)
            prior_months += max(0, _months_between(prior.start_date, prior_end))
        prior_years = prior_months / 12

        title_lower = entry.title.lower()
        is_senior_title = False
        for kw in SENIOR_TITLE_KEYWORDS:
            if not re.search(rf"\b{re.escape(kw)}\b", title_lower):
                continue
            if kw == "lead" and "lead generation" in title_lower:
                continue  # "lead generation" is a sales/marketing term, not a seniority signal
            is_senior_title = True
            break
        if is_senior_title and prior_years < senior_min_years:
            flags.append(
                ConsistencyFlag(
                    kind="seniority_mismatch",
                    detail=(
                        f'"{entry.title}" at {entry.company} claimed after only ~{prior_years:.1f} year(s) of '
                        f'prior experience (O*NET Job Zone {DEFAULT_SENIOR_ZONE} baseline expects ~{senior_min_years:.0f}+)'
                    ),
                    severity="medium",
                )
            )

    all_bullets = [b for e in parsed.experience for b in e.bullets]
    if len(all_bullets) >= 3:
        buzzword_hits = sum(1 for b in all_bullets if any(bw in b.lower() for bw in BUZZWORDS))
        metric_hits = sum(1 for b in all_bullets if METRIC_PATTERN.search(b))
        buzzword_ratio = buzzword_hits / len(all_bullets)
        metric_ratio = metric_hits / len(all_bullets)
        if buzzword_hits >= 2 and buzzword_ratio > metric_ratio:
            flags.append(
                ConsistencyFlag(
                    kind="buzzword_heavy",
                    detail=(
                        f"{buzzword_hits}/{len(all_bullets)} bullets are buzzword-style vs only "
                        f"{metric_hits}/{len(all_bullets)} with quantified metrics"
                    ),
                    severity="low",
                )
            )

    all_bullet_text = " ".join(all_bullets).lower()
    unsupported = [s for s in parsed.skills_claimed if s.lower() not in all_bullet_text]
    if unsupported:
        flags.append(
            ConsistencyFlag(
                kind="unsupported_skill_claims",
                detail=f'{len(unsupported)} claimed skill(s) have no supporting mention in any bullet: {", ".join(unsupported[:10])}',
                severity="low",
            )
        )

    return ConsistencyResult(flags=flags, total_experience_years=total_years)
