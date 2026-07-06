import hashlib

from db.connection import get_conn


def ingest_manual_posting(raw_text: str, title: str, company_name: str, role_query: str | None = None) -> int:
    """Insert a pasted job posting through the same jobs table the ATS ingestors use."""
    external_id = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO companies (name, ats_type, ats_board_token, discovered_via)
            VALUES (?, 'manual', ?, 'manual_paste')
            """,
            (company_name, f"manual-{hashlib.sha256(company_name.encode()).hexdigest()[:12]}"),
        )
        company_id = conn.execute(
            "SELECT id FROM companies WHERE ats_type = 'manual' AND name = ?",
            (company_name,),
        ).fetchone()["id"]

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
