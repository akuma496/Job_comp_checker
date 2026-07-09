"""Seeds the skills taxonomy from data/reference/skills_seed.csv and backfills
normalized_skill_id on every existing requirement — the missing entry point that
made load_seed_taxonomy()/backfill_normalized_skills() dead code before this.

Safe to re-run any time (idempotent) — e.g. after editing skills_seed.csv, or on
a fresh clone before running any matching.

python scripts/load_taxonomy.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import init_db  # noqa: E402
from requirements_extraction.cooccurrence import recompute_cooccurrence_matrix  # noqa: E402
from resume.taxonomy import backfill_normalized_skills, load_seed_taxonomy  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> None:
    init_db()
    load_seed_taxonomy()
    backfill_normalized_skills()
    recompute_cooccurrence_matrix()
    print("Taxonomy loaded and backfilled.")


if __name__ == "__main__":
    main()
