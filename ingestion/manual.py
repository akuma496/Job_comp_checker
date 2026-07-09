import hashlib

from db.connection import get_conn, get_or_create


def ingest_manual_posting(raw_text: str, title: str, company_name: str, role_query: str | None = None) -> int:
    """Insert a pasted job posting through the same jobs table the ATS ingestors use."""
    external_id = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

    with get_conn() as conn:
        company_id, _ = get_or_create(
            conn,
            "companies",
            {"ats_type": "manual", "name": company_name},
            {
                "ats_board_token": f"manual-{hashlib.sha256(company_name.encode()).hexdigest()[:12]}",
                "discovered_via": "manual_paste",
            },
        )

        conn.execute(
            """
            INSERT INTO jobs (company_id, external_id, title, role_query, raw_text, source_type)
            VALUES (?, ?, ?, ?, ?, 'manual')
            ON CONFLICT (company_id, external_id) DO UPDATE SET
                last_seen_at = datetime('now'),
                raw_text = excluded.raw_text
            """,
            (company_id, external_id, title, role_query, raw_text),
        )
        job_id = conn.execute(
            "SELECT id FROM jobs WHERE company_id = ? AND external_id = ?",
            (company_id, external_id),
        ).fetchone()["id"]

    return job_id
