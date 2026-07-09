import itertools
import logging
from collections import defaultdict

from db.connection import get_conn, get_or_create
from requirements_extraction.models import RequirementDraft

logger = logging.getLogger(__name__)


def _normalize(raw_text: str) -> str:
    return raw_text.strip().lower()


def recompute_cooccurrence_matrix() -> None:
    """Rebuild skill_cooccurrence from scratch based on explicit requirements only
    (avoids feedback loops from prior inferences).

    Uses naive lowercase normalization as a placeholder until Milestone 3's real skills
    taxonomy lands (see resume/taxonomy.py's backfill_normalized_skills), which re-maps
    synonyms (e.g. "k8s" vs "kubernetes") onto one canonical skill — re-run this after
    that backfill for a quality boost. Cold-start thinness before then is expected.
    """
    with get_conn() as conn:
        conn.execute("DELETE FROM skill_cooccurrence")

        rows = conn.execute(
            "SELECT id, job_id, raw_text, category, normalized_skill_id FROM requirements WHERE req_type = 'explicit'"
        ).fetchall()

        job_skills: dict[int, set[int]] = defaultdict(set)
        for row in rows:
            skill_id = row["normalized_skill_id"]
            if skill_id is None:
                skill_id, _ = get_or_create(
                    conn, "skills", {"canonical_name": _normalize(row["raw_text"])}, {"category": row["category"]}
                )
                conn.execute("UPDATE requirements SET normalized_skill_id = ? WHERE id = ?", (skill_id, row["id"]))
            job_skills[row["job_id"]].add(skill_id)

        pair_counts: dict[tuple[int, int], int] = defaultdict(int)
        for skill_ids in job_skills.values():
            for a, b in itertools.combinations(sorted(skill_ids), 2):
                pair_counts[(a, b)] += 1

        for (a, b), count in pair_counts.items():
            conn.execute(
                "INSERT INTO skill_cooccurrence (skill_a_id, skill_b_id, cooccurrence_count) VALUES (?, ?, ?)",
                (a, b, count),
            )

    logger.info("recomputed co-occurrence matrix: %d skill pairs", len(pair_counts))


def generate_cooccurring_requirements(job_id: int, threshold: float = 0.4) -> list[RequirementDraft]:
    """For a job's already-normalized explicit skills, surface commonly co-occurring
    partner skills that this job's posting didn't mention, weighted by conditional
    probability P(partner | this skill) computed from the corpus ingested so far."""
    with get_conn() as conn:
        job_skill_rows = conn.execute(
            """
            SELECT DISTINCT normalized_skill_id AS skill_id FROM requirements
            WHERE job_id = ? AND normalized_skill_id IS NOT NULL
            """,
            (job_id,),
        ).fetchall()
        job_skill_ids = {row["skill_id"] for row in job_skill_rows}
        if not job_skill_ids:
            return []

        drafts: dict[int, RequirementDraft] = {}
        for skill_id in job_skill_ids:
            trigger = conn.execute("SELECT canonical_name FROM skills WHERE id = ?", (skill_id,)).fetchone()
            trigger_name = trigger["canonical_name"] if trigger else str(skill_id)

            total_row = conn.execute(
                """
                SELECT COUNT(DISTINCT job_id) AS total FROM requirements
                WHERE req_type = 'explicit' AND normalized_skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
            total = total_row["total"] or 0
            if total == 0:
                continue

            partner_rows = conn.execute(
                """
                SELECT
                    CASE WHEN skill_a_id = ? THEN skill_b_id ELSE skill_a_id END AS partner_id,
                    cooccurrence_count
                FROM skill_cooccurrence
                WHERE skill_a_id = ? OR skill_b_id = ?
                """,
                (skill_id, skill_id, skill_id),
            ).fetchall()

            for partner_row in partner_rows:
                partner_id = partner_row["partner_id"]
                if partner_id in job_skill_ids or partner_id in drafts:
                    continue
                probability = partner_row["cooccurrence_count"] / total
                if probability < threshold:
                    continue
                skill = conn.execute(
                    "SELECT canonical_name, category FROM skills WHERE id = ?", (partner_id,)
                ).fetchone()
                drafts[partner_id] = RequirementDraft(
                    raw_text=skill["canonical_name"],
                    category=skill["category"] or "core_skill",
                    confidence=round(probability, 2),
                    source_detail=f'co-occurs with "{trigger_name}" in {round(probability * 100)}% of postings requiring it',
                )

    return list(drafts.values())
