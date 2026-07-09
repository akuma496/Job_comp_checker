"""Small read queries shared across multiple dashboard views, so each one doesn't
hand-roll its own copy of the same SQL."""

from db.connection import get_conn


def load_resume_versions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT resume_versions.id, resumes.display_name, resume_versions.version_label
            FROM resume_versions JOIN resumes ON resumes.id = resume_versions.resume_id
            ORDER BY resume_versions.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]
