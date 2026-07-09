import json
from dataclasses import asdict, dataclass

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


@dataclass
class _ResumeContext:
    """Everything about a resume_version that's invariant across every job it's
    matched against — computed once and reused, instead of once per job."""

    phrases: list[str]
    phrase_embeddings: object  # np.ndarray | None
    resume_skill_ids: set[int]
    credibility_score: float | None
    credibility_detail: dict | None


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


def _load_resume_context(resume_version_id: int) -> _ResumeContext:
    with get_conn() as conn:
        resume_version = conn.execute(
            "SELECT * FROM resume_versions WHERE id = ?", (resume_version_id,)
        ).fetchone()
        if resume_version is None:
            raise ValueError(f"No resume_version with id {resume_version_id}")
        resume_version = dict(resume_version)
        candidates = _load_candidates(conn)

    phrases = _resume_phrases(resume_version)
    resume_skill_ids = _resume_skill_ids(phrases, candidates)
    phrase_embeddings = embed_texts(phrases) if phrases else None
    credibility_score, credibility_detail = _compute_credibility(resume_version)

    return _ResumeContext(
        phrases=phrases,
        phrase_embeddings=phrase_embeddings,
        resume_skill_ids=resume_skill_ids,
        credibility_score=credibility_score,
        credibility_detail=credibility_detail,
    )


def _score_job(resume_version_id: int, job_id: int, context: _ResumeContext) -> dict:
    with get_conn() as conn:
        requirements = conn.execute("SELECT * FROM requirements WHERE job_id = ?", (job_id,)).fetchall()
        requirements = [dict(r) for r in requirements]

    phrases = context.phrases
    phrase_embeddings = context.phrase_embeddings
    resume_skill_ids = context.resume_skill_ids

    category_scores = {cat: {"job_weighted": 0.0, "resume_weighted": 0.0} for cat in CATEGORIES}
    gap_list = []
    job_weighted_total = 0.0
    resume_weighted_total = 0.0

    # Keyword pass first (cheap), so only the requirements that actually need the
    # embedding fallback get embedded — and those get embedded in one batched call
    # instead of one model.encode() per requirement.
    keyword_covered = [
        req["normalized_skill_id"] is not None and req["normalized_skill_id"] in resume_skill_ids
        for req in requirements
    ]
    fallback_indices = [i for i, covered in enumerate(keyword_covered) if not covered]
    fallback_position = {orig_idx: pos for pos, orig_idx in enumerate(fallback_indices)}
    fallback_embeddings = (
        embed_texts([requirements[i]["raw_text"] for i in fallback_indices])
        if fallback_indices and phrases
        else None
    )

    for req_idx, req in enumerate(requirements):
        weight = REQ_TYPE_WEIGHTS[req["req_type"]]
        category = req["category"]
        category_scores[category]["job_weighted"] += weight
        job_weighted_total += weight

        covered = False
        match_type = "none"
        match_confidence = 0.0
        matched_phrase = None

        if keyword_covered[req_idx]:
            covered = True
            match_type = "keyword"
            match_confidence = 1.0
        elif phrases:
            req_embedding = fallback_embeddings[fallback_position[req_idx]]
            score, idx = max_cosine_similarity(req_embedding, phrase_embeddings)
            if score >= EMBEDDING_MATCH_THRESHOLD:
                covered = True
                match_type = "embedding"
                match_confidence = score
                matched_phrase = phrases[idx]

        if covered:
            category_scores[category]["resume_weighted"] += weight
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
        "credibility_score": context.credibility_score,
        "credibility_detail": context.credibility_detail,
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
                context.credibility_score,
                json.dumps(context.credibility_detail) if context.credibility_detail else None,
            ),
        )

    return result


def compute_match(resume_version_id: int, job_id: int) -> dict:
    context = _load_resume_context(resume_version_id)
    return _score_job(resume_version_id, job_id, context)


def compute_match_batch(resume_version_id: int, job_ids: list[int], progress_callback=None) -> dict[int, dict | Exception]:
    """Same as calling compute_match() once per job_id, but the resume-side setup
    (phrase list, taxonomy candidates, phrase embeddings, credibility scoring) is
    computed once for the whole batch instead of redundantly per job.

    progress_callback(index, total, job_id), if given, is called after each job is
    scored (for a UI progress bar). A per-job exception is caught, stored as the
    result for that job_id, and does not stop the rest of the batch."""
    context = _load_resume_context(resume_version_id)
    results: dict[int, dict | Exception] = {}
    for i, job_id in enumerate(job_ids):
        try:
            results[job_id] = _score_job(resume_version_id, job_id, context)
        except Exception as exc:
            results[job_id] = exc
        if progress_callback:
            progress_callback(i, len(job_ids), job_id)
    return results
