"""Downloads the free, public O*NET database (no auth required) and extracts just the
files needed for the credibility check's statistical-plausibility baseline.

python scripts/fetch_reference_data.py [--force]
"""

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from config import BASE_DIR  # noqa: E402

ONET_ZIP_URL = "https://www.onetcenter.org/dl_files/database/db_30_3_text.zip"
REFERENCE_DIR = BASE_DIR / "data" / "reference"
ONET_DIR = REFERENCE_DIR / "onet"
NEEDED_FILES = ["Job Zone Reference.txt", "Job Zones.txt"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-download even if files already exist")
    args = parser.parse_args()

    ONET_DIR.mkdir(parents=True, exist_ok=True)
    already_present = all((ONET_DIR / "db_30_3_text" / name).exists() for name in NEEDED_FILES)
    if already_present and not args.force:
        print("O*NET reference files already present, skipping download (use --force to redo).")
        return

    zip_path = REFERENCE_DIR / "onet_db.zip"
    print(f"Downloading {ONET_ZIP_URL} ...")
    response = requests.get(ONET_ZIP_URL, timeout=60)
    response.raise_for_status()
    zip_path.write_bytes(response.content)

    with zipfile.ZipFile(zip_path) as zf:
        members = [f"db_30_3_text/{name}" for name in NEEDED_FILES]
        zf.extractall(ONET_DIR, members=members)

    zip_path.unlink()
    print(f"Extracted {NEEDED_FILES} into {ONET_DIR}")


if __name__ == "__main__":
    main()
