"""Parses the downloaded O*NET Job Zone reference file into a local DB table used by
the credibility check's title-vs-experience baseline.

The O*NET text is prose (e.g. "a considerable amount of work-related skill... four
year bachelor's degree... work for several years"), not clean numbers, so the numeric
min_years_estimate per zone below is a documented human-derived approximation from
that same text, not an arbitrary guess:
  Zone 2 (Job Zone 1-2, "little to some preparation"): ~0 years
  Zone 3 ("medium preparation", 1-2 yrs vocational/apprenticeship): ~2 years
  Zone 4 ("considerable preparation", bachelor's + several years): ~4 years
  Zone 5 ("extensive preparation", 5+ years / graduate study): ~7 years

python scripts/build_reference_stats.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR  # noqa: E402
from db.connection import get_conn, init_db  # noqa: E402

ONET_DIR = BASE_DIR / "data" / "reference" / "onet" / "db_30_3_text"
MIN_YEARS_BY_ZONE = {2: 0.0, 3: 2.0, 4: 4.0, 5: 7.0}


def main() -> None:
    init_db()
    path = ONET_DIR / "Job Zone Reference.txt"
    if not path.exists():
        print(f"Missing {path} — run scripts/fetch_reference_data.py first.")
        return

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    with get_conn() as conn:
        for row in rows:
            zone = int(row["Job Zone"])
            conn.execute(
                """
                INSERT INTO onet_job_zones (zone, name, typical_experience_text, typical_education_text, min_years_estimate)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (zone) DO UPDATE SET
                    name = excluded.name,
                    typical_experience_text = excluded.typical_experience_text,
                    typical_education_text = excluded.typical_education_text,
                    min_years_estimate = excluded.min_years_estimate
                """,
                (zone, row["Name"], row["Experience"], row["Education"], MIN_YEARS_BY_ZONE.get(zone, 0.0)),
            )

    print(f"Loaded {len(rows)} O*NET job zone(s) into onet_job_zones.")


if __name__ == "__main__":
    main()
