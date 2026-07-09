import csv
import logging
import re
from pathlib import Path

from rapidfuzz import fuzz, process

from config import BASE_DIR
from db.connection import get_conn

logger = logging.getLogger(__name__)

SEED_CSV_PATH = BASE_DIR / "data" / "reference" / "skills_seed.csv"
FUZZY_SCORE_CUTOFF = 90


def _read_seed_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_seed_taxonomy(csv_path: Path = SEED_CSV_PATH) -> None:
    """Idempotent: upserts canonical skills + aliases from the seed CSV."""
    rows = _read_seed_rows(csv_path)

    with get_conn() as conn:
        for row in rows:
            canonical_name = row["canonical_name"].strip()
            category = row["category"].strip()

            existing = conn.execute(
                "SELECT id FROM skills WHERE canonical_name = ?", (canonical_name,)
            ).fetchone()
            if existing:
                skill_id = existing["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO skills (canonical_name, category) VALUES (?, ?)",
                    (canonical_name, category),
                )
                skill_id = cursor.lastrowid

            aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
            for alias in aliases:
                conn.execute(
                    "INSERT OR IGNORE INTO skill_aliases (alias_text, skill_id) VALUES (?, ?)",
                    (alias, skill_id),
                )

    logger.info("loaded seed taxonomy: %d canonical skills", len(rows))


def _load_candidates(conn, csv_path: Path = SEED_CSV_PATH) -> list[tuple[str, int]]:
    """(lowercased term, skill_id) pairs built ONLY from the curated seed CSV's canonical
    names + aliases — deliberately excludes the noisy per-phrase skills auto-created by
    Milestone 2's cold-start co-occurrence bootstrap, since those are just lowercased
    copies of arbitrary requirement text and would otherwise "self-match" trivially.
    Sorted longest-first so substring matching prefers more specific terms
    (e.g. "JavaScript" over "Java")."""
    rows = _read_seed_rows(csv_path)
    candidates = []
    for row in rows:
        canonical_name = row["canonical_name"].strip()
        skill = conn.execute(
            "SELECT id FROM skills WHERE canonical_name = ?", (canonical_name,)
        ).fetchone()
        if skill is None:
            continue
        skill_id = skill["id"]
        candidates.append((canonical_name.lower(), skill_id))
        for alias in (row.get("aliases") or "").split("|"):
            alias = alias.strip()
            if alias:
                candidates.append((alias.lower(), skill_id))

    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    return candidates


def normalize_skill(raw_text: str, candidates: list[tuple[str, int]] | None = None) -> int | None:
    """Match a free-text requirement/skill phrase to a canonical seed skill id.

    Tries whole-word substring containment first (raw_text is usually a longer phrase
    like "Strong Python skills", not just "Python"), then falls back to fuzzy matching
    for typos/near-misses. Returns None if nothing in the curated taxonomy matches —
    callers should leave the existing normalized_skill_id alone in that case.
    """
    text_lower = raw_text.lower()

    if candidates is None:
        with get_conn() as conn:
            candidates = _load_candidates(conn)

    for term, skill_id in candidates:
        if len(term) < 2:
            continue
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text_lower):
            return skill_id

    terms = [term for term, _ in candidates if len(term) >= 3]
    if not terms:
        return None
    match = process.extractOne(text_lower, terms, scorer=fuzz.token_set_ratio, score_cutoff=FUZZY_SCORE_CUTOFF)
    if match is None:
        return None
    matched_term = match[0]
    for term, skill_id in candidates:
        if term == matched_term:
            return skill_id
    return None


def find_all_skills(text: str, candidates: list[tuple[str, int]] | None = None) -> set[int]:
    """Find every taxonomy skill mentioned anywhere in a longer piece of text (e.g. a
    resume's full bullet list), unlike normalize_skill which assumes the input is about
    a single skill and stops at the first (longest) match — wrong here, since a bullet
    like "Built Python microservices" legitimately references two distinct skills."""
    text_lower = text.lower()
    if candidates is None:
        with get_conn() as conn:
            candidates = _load_candidates(conn)

    found = set()
    for term, skill_id in candidates:
        if len(term) < 2:
            continue
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text_lower):
            found.add(skill_id)
    return found


def backfill_normalized_skills() -> int:
    """Re-normalize every requirement's raw_text against the seed taxonomy, upgrading
    from the naive per-phrase bootstrap skills created during Milestone 2's cold start.
    Leaves normalized_skill_id untouched when nothing in the curated taxonomy matches."""
    updated = 0
    with get_conn() as conn:
        candidates = _load_candidates(conn)
        rows = conn.execute("SELECT id, raw_text, normalized_skill_id FROM requirements").fetchall()

        for row in rows:
            skill_id = normalize_skill(row["raw_text"], candidates=candidates)
            if skill_id is not None and skill_id != row["normalized_skill_id"]:
                conn.execute(
                    "UPDATE requirements SET normalized_skill_id = ? WHERE id = ?",
                    (skill_id, row["id"]),
                )
                updated += 1

    logger.info("backfilled normalized_skill_id for %d requirement(s)", updated)
    return updated
