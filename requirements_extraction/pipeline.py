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


def _store_cooccurring(job_id: int) -> list[RequirementDraft]:
    """Assumes the co-occurrence matrix is already up to date — caller is
    responsible for calling recompute_cooccurrence_matrix() first. Best-effort:
    a failure here shouldn't lose the explicit/inferred requirements already saved."""
    try:
        cooccurring_drafts = generate_cooccurring_requirements(job_id)
    except Exception:
        logger.exception("co-occurrence step failed for job %d, continuing without it", job_id)
        cooccurring_drafts = []

    with get_conn() as conn:
        conn.execute("DELETE FROM requirements WHERE job_id = ? AND req_type = 'cooccurring'", (job_id,))
        _insert_drafts(conn, job_id, "cooccurring", cooccurring_drafts)
    return cooccurring_drafts


def process_job(job_id: int, recompute_cooccurrence: bool = True) -> dict:
    """Idempotent: clears this job's prior requirements rows before reinserting,
    so reruns after prompt tweaks don't duplicate.

    recompute_cooccurrence=False skips the (expensive, full-corpus O(n^2)) matrix
    rebuild here — used by process_all_jobs, which rebuilds once after its whole
    batch instead of once per job."""
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError(f"No job with id {job_id}")

    explicit_drafts, inferred_drafts = extract_requirements(job)

    with get_conn() as conn:
        _clear_requirements(conn, job_id)
        _insert_drafts(conn, job_id, "explicit", explicit_drafts)
        _insert_drafts(conn, job_id, "context_inferred", inferred_drafts)

    cooccurring_drafts = []
    if recompute_cooccurrence:
        recompute_cooccurrence_matrix()
        cooccurring_drafts = _store_cooccurring(job_id)

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


def finalize_cooccurrence_for_batch(job_ids: list[int]) -> None:
    """One matrix rebuild + one co-occurring pass across all of job_ids, instead of
    rebuilding the full O(n^2) matrix from scratch after every single job. Callers
    that process many jobs in a loop (process_all_jobs, the dashboard's bulk
    re-extract button) should call process_job(..., recompute_cooccurrence=False)
    in the loop and then this once at the end."""
    if not job_ids:
        return
    recompute_cooccurrence_matrix()
    for job_id in job_ids:
        _store_cooccurring(job_id)


def process_all_jobs(only_unprocessed: bool = True) -> None:
    """`only_unprocessed` matches the dashboard's own "incomplete" definition
    (missing explicit rows specifically) rather than "any row exists" — a job that
    got 0 explicit requirements from a Claude hiccup but has context_inferred/
    cooccurring rows would otherwise be silently skipped forever on CLI reruns
    while the dashboard would still (correctly) offer to re-extract it."""
    with get_conn() as conn:
        if only_unprocessed:
            rows = conn.execute(
                """
                SELECT id FROM jobs WHERE status = 'active'
                AND id NOT IN (SELECT DISTINCT job_id FROM requirements WHERE req_type = 'explicit')
                """
            ).fetchall()
        else:
            rows = conn.execute("SELECT id FROM jobs WHERE status = 'active'").fetchall()

    job_ids = [row["id"] for row in rows]
    for job_id in job_ids:
        process_job(job_id, recompute_cooccurrence=False)
    finalize_cooccurrence_for_batch(job_ids)
