"""python scripts/show_requirements.py --job-id 5"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import get_conn  # noqa: E402

SECTION_TITLES = {
    "explicit": "Explicit",
    "context_inferred": "Context-Inferred",
    "cooccurring": "Co-occurring",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args()

    with get_conn() as conn:
        job = conn.execute("SELECT title FROM jobs WHERE id = ?", (args.job_id,)).fetchone()
        if job is None:
            print(f"No job with id {args.job_id}")
            return

        print(f"=== Requirements for job {args.job_id}: {job['title']} ===\n")

        for req_type, title in SECTION_TITLES.items():
            rows = conn.execute(
                """
                SELECT raw_text, category, confidence, source_detail FROM requirements
                WHERE job_id = ? AND req_type = ?
                ORDER BY confidence DESC
                """,
                (args.job_id, req_type),
            ).fetchall()

            print(f"-- {title} ({len(rows)}) --")
            if not rows:
                print("  (none)")
            for row in rows:
                line = f"  [{row['category']}] {row['raw_text']}  (confidence={row['confidence']:.2f})"
                print(line)
                if row["source_detail"]:
                    print(f"      why: {row['source_detail']}")
            print()


if __name__ == "__main__":
    main()
