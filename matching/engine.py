import json
from dataclasses import asdict

from db.connection import get_conn
from matching.embeddings import embed_texts, max_cosine_similarity
from requirements_extraction.models import CATEGORIES
from resume.credibility import check_internal_consistency
from resume.parser import parsed_resume_from_json
from resume.taxonomy import _load_candidates, find_all_skills

REQ_TYPE_WEIGHTS = {"explicit": 1.0, "context_inferred": 0.6, "cooccurring": 0.3}
REQ_TYPE_PRIORITY = {"explicit": 0, "context_inferred": 1, "cooccurring": 2}
# Lowered from 0.55: all-MiniLM-L6-v2 often scores clean, correct paraphrases
# (e.g. "Led a 6-person engineering team" vs "ability to guide and inspire a team")
# around 0.50, so 0.55 was rejecting legitimate matches.
EMBEDDING_MATCH_THRESHOLD = 0.50
SEVERITY_PENALTY = {"low": 5, "medium": 10, "high": 20}


def _compute_credibility(resume_version: dict) -> tuple[float | None, dict | None]:
    """Credibility is a property of the resume alone, not the job — recomputed
    identically for every match against this resume_version. Returns None until the
    resume has been structured (parsed_json populated), since the checks need real
    experience-entry dates, not just raw text."""
    if not resume_version["parsed_json"]:
        return None, None

    parsed = parsed_resume_from_json(resume_version["parsed_json"])
    consistency = check_internal_consistency(parsed)
    penalty = sum(SEVERITY_PENALTY[f.severity] for f in consistency.flags)
    score = max(0.0, 100.0 - penalty)
    detail = {
        "flags": [asdict(f) for f in consistency.flags],
        "total_experience_years": consistency.total_experience_years,
    }
    return score, detail


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
    credibility_score, credibility_detail = _compute_credibility(resume_version)

    result = {
        "overall_score": overall_score,
        "category_scores": category_scores,
        "gap_list": gap_list,
        "credibility_score": credibility_score,
        "credibility_detail": credibility_detail,
    }

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO matches (
                resume_version_id, job_id, overall_score, category_scores_json, gap_list_json,
                credibility_score, credibility_detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (resume_version_id, job_id) DO UPDATE SET
                computed_at = datetime('now'),
                overall_score = excluded.overall_score,
                category_scores_json = excluded.category_scores_json,
                gap_list_json = excluded.gap_list_json,
                credibility_score = excluded.credibility_score,
                credibility_detail_json = excluded.credibility_detail_json
            """,
            (
                resume_version_id,
                job_id,
                overall_score,
                json.dumps(category_scores),
                json.dumps(gap_list),
                credibility_score,
                json.dumps(credibility_detail) if credibility_detail else None,
            ),
        )

    return result
