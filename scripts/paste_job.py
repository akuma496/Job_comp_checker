"""Demonstrates the manual-paste ingestion path (feeds the same jobs table as the ATS crawler).

python scripts/paste_job.py --company "Acme Corp" --title "AI Engineer" --file posting.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import init_db  # noqa: E402
from ingestion.manual import ingest_manual_posting  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--file", required=True, help="Path to a text file containing the pasted posting")
    parser.add_argument("--role-query", default=None)
    args = parser.parse_args()

    init_db()
    raw_text = Path(args.file).read_text(encoding="utf-8")
    job_id = ingest_manual_posting(raw_text, args.title, args.company, args.role_query)
    print(f"Ingested manual posting as job id {job_id}")


if __name__ == "__main__":
    main()
