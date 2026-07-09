import logging

from db.connection import get_conn, init_db
from ingestion.discovery import discover_boards
from ingestion.registry import ATS_REGISTRY

logger = logging.getLogger(__name__)


def _title_matches_role(title: str, role_title: str) -> bool:
    title_lower = title.lower()
    return all(word in title_lower for word in role_title.lower().split())


def _upsert_job(conn, company_id: int, posting, role_title: str) -> None:
    conn.execute(
        """
        INSERT INTO jobs (
            company_id, external_id, title, role_query, location, remote_flag,
            seniority_raw, department, posting_url, raw_text, source_type, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ats', 'active')
        ON CONFLICT (company_id, external_id) DO UPDATE SET
            title = excluded.title,
            raw_text = excluded.raw_text,
            last_seen_at = datetime('now'),
            status = 'active'
        """,
        (
            company_id,
            posting.external_id,
            posting.title,
            role_title,
            posting.location,
            int(posting.remote_flag),
            posting.seniority_raw,
            posting.department,
            posting.posting_url,
            posting.raw_text,
        ),
    )


def run_pipeline(role_title: str) -> dict:
    """Discover boards for role_title across every registered ATS, fetch each
    board's postings, upsert matching jobs, and mark postings that vanished as removed."""
    init_db()

    stats = {"new_companies": 0, "jobs_seen": 0, "jobs_matched": 0}

    for ats_type in ATS_REGISTRY:
        new_tokens = discover_boards(role_title, ats_type)
        stats["new_companies"] += len(new_tokens)
        logger.info("discovered %d new %s boards", len(new_tokens), ats_type)

    with get_conn() as conn:
        companies = conn.execute(
            "SELECT id, ats_board_token, ats_type FROM companies WHERE ats_type != 'manual'"
        ).fetchall()

    ingestor_instances = {ats_type: cls() for ats_type, cls in ATS_REGISTRY.items()}

    for company in companies:
        ingestor = ingestor_instances.get(company["ats_type"])
        if ingestor is None:
            continue

        postings = ingestor.fetch_postings(company["ats_board_token"])
        stats["jobs_seen"] += len(postings)
        matching = [p for p in postings if _title_matches_role(p.title, role_title)]
        stats["jobs_matched"] += len(matching)

        seen_external_ids = {p.external_id for p in matching}
        with get_conn() as conn:
            for posting in matching:
                _upsert_job(conn, company["id"], posting, role_title)

            # Key this off `postings` (the raw fetch), not `seen_external_ids` (the
            # role-filtered subset) — a board can genuinely have zero postings that
            # still match role_title while the fetch itself succeeded, and we still
            # want previously-tracked jobs marked removed in that case. Only skip
            # when `postings` is empty too, since fetch_postings() returns [] on a
            # failed request as well as on a real empty board, and we'd rather not
            # mark things removed on an ambiguous/failed fetch.
            if postings:
                if seen_external_ids:
                    placeholders = ",".join("?" * len(seen_external_ids))
                    conn.execute(
                        f"""
                        UPDATE jobs SET status = 'removed'
                        WHERE company_id = ? AND source_type = 'ats'
                          AND external_id NOT IN ({placeholders})
                        """,
                        (company["id"], *seen_external_ids),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status = 'removed' WHERE company_id = ? AND source_type = 'ats'",
                        (company["id"],),
                    )

    return stats
