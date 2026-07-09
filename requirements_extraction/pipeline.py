import logging

from db.connection import get_conn
from requirements_extraction.combined import extract_requirements
from requirements_extraction.cooccurrence import generate_cooccurring_requirements, recompute_cooccurrence_matrix
from requirements_extraction.models import RequirementDraft

logger = logging.getLogger(__name__)

REQ_TYPES = ("explicit", "context_inferred", "cooccurring")


def _clear_requirements(conn, job_id: int) -> None:
    conn.execute(
        "DELETE FROM requirements WHERE job_id = ? AND req_type IN (?, ?, ?)",
        (job_id, *REQ_TYPES),
    )


def _insert_drafts(conn, job_id: int, req_type: str, drafts: list[RequirementDraft]) -> None:
    for draft in drafts:
        conn.execute(
            """
            INSERT INTO requirements (job_id, req_type, category, raw_text, confidence, source_detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, req_type, draft.category, draft.raw_text, draft.confidence, draft.source_detail),
        )


def process_job(job_id: int) -> dict:
    """Idempotent: clears this job's prior requirements rows before reinserting,
    so reruns after prompt tweaks don't duplicate."""
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError(f"No job with id {job_id}")

    explicit_drafts, inferred_drafts = extract_requirements(job)

    with get_conn() as conn:
        _clear_requirements(conn, job_id)
        _insert_drafts(conn, job_id, "explicit", explicit_drafts)
        _insert_drafts(conn, job_id, "context_inferred", inferred_drafts)

    # Best-effort: co-occurrence needs the matrix rebuilt over whatever explicit
    # requirements exist so far across the corpus (thin/cold-start early on, fine).
    try:
        recompute_cooccurrence_matrix()
        cooccurring_drafts = generate_cooccurring_requirements(job_id)
    except Exception:
        logger.exception("co-occurrence step failed for job %d, continuing without it", job_id)
        cooccurring_drafts = []

    with get_conn() as conn:
        conn.execute("DELETE FROM requirements WHERE job_id = ? AND req_type = 'cooccurring'", (job_id,))
        _insert_drafts(conn, job_id, "cooccurring", cooccurring_drafts)

    logger.info(
        "job %d: %d explicit, %d context-inferred, %d cooccurring",
        job_id,
        len(explicit_drafts),
        len(inferred_drafts),
        len(cooccurring_drafts),
    )
    return {
        "explicit": len(explicit_drafts),
        "context_inferred": len(inferred_drafts),
        "cooccurring": len(cooccurring_drafts),
    }


def process_all_jobs(only_unprocessed: bool = True) -> None:
    with get_conn() as conn:
        if only_unprocessed:
            rows = conn.execute(
                """
                SELECT id FROM jobs WHERE status = 'active'
                AND id NOT IN (SELECT DISTINCT job_id FROM requirements)
                """
            ).fetchall()
        else:
            rows = conn.execute("SELECT id FROM jobs WHERE status = 'active'").fetchall()

    for row in rows:
        process_job(row["id"])
