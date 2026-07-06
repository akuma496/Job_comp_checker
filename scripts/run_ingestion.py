"""python scripts/run_ingestion.py --role "AI Engineer" """

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.pipeline import run_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, help='Role title to search for, e.g. "AI Engineer"')
    args = parser.parse_args()

    stats = run_pipeline(args.role)
    print(f"New companies discovered: {stats['new_companies']}")
    print(f"Postings seen across boards: {stats['jobs_seen']}")
    print(f"Postings matching '{args.role}': {stats['jobs_matched']}")


if __name__ == "__main__":
    main()
