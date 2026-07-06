"""python scripts/list_jobs.py [--status active]"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import get_conn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default=None, help="Filter by job status (active/closed/removed)")
    args = parser.parse_args()

    query = """
        SELECT jobs.id, companies.name AS company, jobs.title, jobs.location,
               jobs.source_type, jobs.status, jobs.last_seen_at
        FROM jobs JOIN companies ON companies.id = jobs.company_id
    """
    params: tuple = ()
    if args.status:
        query += " WHERE jobs.status = ?"
        params = (args.status,)
    query += " ORDER BY jobs.last_seen_at DESC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No jobs found. Run scripts/run_ingestion.py first.")
        return

    for row in rows:
        print(
            f"[{row['id']:>4}] {row['company']:<25} {row['title']:<45} "
            f"{row['location'] or '':<20} {row['source_type']:<7} {row['status']:<8} {row['last_seen_at']}"
        )


if __name__ == "__main__":
    main()
