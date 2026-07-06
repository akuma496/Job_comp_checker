"""python scripts/run_extraction.py --all
python scripts/run_extraction.py --job-id 5
python scripts/run_extraction.py --all --force   (reprocess even already-processed jobs)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from requirements_extraction.pipeline import process_all_jobs, process_job  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Process all jobs missing requirements")
    group.add_argument("--job-id", type=int, help="Process a single job by id (always reprocesses)")
    parser.add_argument("--force", action="store_true", help="With --all, reprocess jobs that already have requirements")
    args = parser.parse_args()

    if args.job_id:
        stats = process_job(args.job_id)
        print(stats)
    else:
        process_all_jobs(only_unprocessed=not args.force)
        print("Done.")


if __name__ == "__main__":
    main()
