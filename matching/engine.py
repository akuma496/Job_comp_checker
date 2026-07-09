import json

from db.connection import get_conn
from matching.embeddings import embed_texts, max_cosine_similarity
from requirements_extraction.models import CATEGORIES
from resume.taxonomy import _load_candidates, find_all_skills

REQ_TYPE_WEIGHTS = {"explicit": 1.0, "context_inferred": 0.6, "cooccurring": 0.3}
REQ_TYPE_PRIORITY = {"explicit": 0, "context_inferred": 1, "cooccurring": 2}
EMBEDDING_MATCH_THRESHOLD = 0.55


def _resume_phrases(resume_version: dict) -> list[str]:
    """Prefer structured data (skills_claimed + bullets) when available; fall back to
    naive line-splitting of the raw text for resumes that haven't been structured yet."""
    if resume_version["parsed_json"]:
        data = json.loads(resume_version["parsed_json"])
        phrases = list(data.get("skills_claimed", []))
        for exp in data.get("experience", []):
            phrases.extend(exp.get("bullets", []))
        return [p for p in phrases if p and p.strip()]

    raw_text = resume_version["raw_text"] or ""
    return [line.strip() for line in raw_text.splitlines() if line.strip()]


def _resume_skill_ids(phrases: list[str], candidates) -> set[int]:
    return find_all_skills("\n".join(phrases), candidates=candidates)


def compute_match(resume_version_id: int, job_id: int) -> dict:
    with get_conn() as conn:
        resume_version = conn.execute(
            "SELECT * FROM resume_versions WHERE id = ?", (resume_version_id,)
        ).fetchone()
        if resume_version is None:
            raise ValueError(f"No resume_version with id {resume_version_id}")
        resume_version = dict(resume_version)

        requirements = conn.execute(
            "SELECT * FROM requirements WHERE job_id = ?", (job_id,)
        ).fetchall()
        requirements = [dict(r) for r in requirements]

        candidates = _load_candidates(conn)

    phrases = _resume_phrases(resume_version)
    resume_skill_ids = _resume_skill_ids(phrases, candidates)

    phrase_embeddings = embed_texts(phrases) if phrases else None

    category_scores = {
        cat: {"job_weighted": 0.0, "resume_weighted": 0.0, "counts": {t: {"total": 0, "covered": 0} for t in REQ_TYPE_WEIGHTS}}
        for cat in CATEGORIES
    }
    gap_list = []
    job_weighted_total = 0.0
    resume_weighted_total = 0.0

    for req in requirements:
        weight = REQ_TYPE_WEIGHTS[req["req_type"]]
        category = req["category"]
        category_scores[category]["job_weighted"] += weight
        category_scores[category]["counts"][req["req_type"]]["total"] += 1
        job_weighted_total += weight

        covered = False
        match_type = "none"
        match_confidence = 0.0
        matched_phrase = None

        if req["normalized_skill_id"] is not None and req["normalized_skill_id"] in resume_skill_ids:
            covered = True
            match_type = "keyword"
            match_confidence = 1.0
        elif phrases:
            req_embedding = embed_texts([req["raw_text"]])[0]
            score, idx = max_cosine_similarity(req_embedding, phrase_embeddings)
            if score >= EMBEDDING_MATCH_THRESHOLD:
                covered = True
                match_type = "embedding"
                match_confidence = score
                matched_phrase = phrases[idx]

        if covered:
            category_scores[category]["resume_weighted"] += weight
            category_scores[category]["counts"][req["req_type"]]["covered"] += 1
            resume_weighted_total += weight

        # Surface both hard misses and weak (embedding-only) matches in the gap list —
        # a keyword hit is confident enough to omit, everything else is worth a look.
        if match_type != "keyword":
            gap_list.append(
                {
                    "requirement_id": req["id"],
                    "req_type": req["req_type"],
                    "category": category,
                    "raw_text": req["raw_text"],
                    "status": "weak_match" if covered else "missing",
                    "requirement_confidence": req["confidence"],
                    "match_confidence": round(match_confidence, 2),
                    "matched_phrase": matched_phrase,
                    "source_detail": req["source_detail"],
                }
            )

    gap_list.sort(key=lambda g: (REQ_TYPE_PRIORITY[g["req_type"]], -g["requirement_confidence"]))

    overall_score = (resume_weighted_total / job_weighted_total) if job_weighted_total > 0 else None

    result = {
        "overall_score": overall_score,
        "category_scores": category_scores,
        "gap_list": gap_list,
    }

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO matches (resume_version_id, job_id, overall_score, category_scores_json, gap_list_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (resume_version_id, job_id) DO UPDATE SET
                computed_at = datetime('now'),
                overall_score = excluded.overall_score,
                category_scores_json = excluded.category_scores_json,
                gap_list_json = excluded.gap_list_json
            """,
            (resume_version_id, job_id, overall_score, json.dumps(category_scores), json.dumps(gap_list)),
        )

    return result
