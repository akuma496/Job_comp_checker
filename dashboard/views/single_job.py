import json

import streamlit as st

from dashboard.charts import REQ_TYPE_COLORS, REQ_TYPE_LABELS, build_radar_figure
from db.connection import get_conn
from matching.engine import compute_match
from requirements_extraction.models import CATEGORIES


def _load_jobs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT jobs.id, jobs.title, companies.name AS company FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.status = 'active'
            ORDER BY jobs.last_seen_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _load_resume_versions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT resume_versions.id, resumes.display_name, resume_versions.version_label
            FROM resume_versions JOIN resumes ON resumes.id = resume_versions.resume_id
            ORDER BY resume_versions.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _load_existing_match(resume_version_id: int, job_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM matches WHERE resume_version_id = ? AND job_id = ?",
            (resume_version_id, job_id),
        ).fetchone()
    return dict(row) if row else None


def _result_from_row(row: dict) -> dict:
    return {
        "overall_score": row["overall_score"],
        "category_scores": json.loads(row["category_scores_json"]),
        "gap_list": json.loads(row["gap_list_json"]),
        "credibility_score": row["credibility_score"],
        "credibility_detail": json.loads(row["credibility_detail_json"]) if row["credibility_detail_json"] else None,
    }


def render() -> None:
    st.header("Single Job Match")
    st.caption("Compare one resume version against one job's requirements.")

    jobs = _load_jobs()
    resume_versions = _load_resume_versions()
    if not jobs:
        st.info("No jobs ingested yet.")
        return
    if not resume_versions:
        st.info('No resumes uploaded yet. Add one on the "Resumes" page.')
        return

    jump_job_id = st.session_state.pop("_jump_to_job_id", None)
    jump_resume_id = st.session_state.pop("_jump_to_resume_version_id", None)
    if jump_job_id is not None:
        st.session_state["single_job_search"] = ""

    search_term = st.text_input(
        "Search jobs (title or company)", placeholder='e.g. "AI Engineer" or "mistral"', key="single_job_search"
    )
    filtered_jobs = [
        j for j in jobs if search_term.lower() in j["title"].lower() or search_term.lower() in j["company"].lower()
    ]
    if search_term and not filtered_jobs:
        st.warning("No jobs match that search.")
        return

    job_options = {f"{j['title']} — {j['company']} (#{j['id']})": j["id"] for j in filtered_jobs}
    resume_options = {f"{r['display_name']} / {r['version_label']} (#{r['id']})": r["id"] for r in resume_versions}
    job_labels = list(job_options.keys())
    resume_labels = list(resume_options.keys())

    default_job_index = next((i for i, l in enumerate(job_labels) if job_options[l] == jump_job_id), 0)
    default_resume_index = next((i for i, l in enumerate(resume_labels) if resume_options[l] == jump_resume_id), 0)

    col1, col2 = st.columns(2)
    with col1:
        job_label = st.selectbox("Job", job_labels, index=default_job_index)
    with col2:
        resume_label = st.selectbox("Resume version", resume_labels, index=default_resume_index)

    job_id = job_options[job_label]
    resume_version_id = resume_options[resume_label]

    existing = _load_existing_match(resume_version_id, job_id)
    recompute = st.button("Compute / Recompute Match", help="Local embeddings only — no API cost")

    if recompute or existing is None:
        with st.spinner("Computing match (local embeddings, no API cost)..."):
            result = compute_match(resume_version_id, job_id)
    else:
        result = _result_from_row(existing)

    if result["overall_score"] is None:
        st.warning("This job has no requirements extracted yet — run extraction first (Pipeline Controls page).")
        return

    st.metric("Overall Match Score", f"{result['overall_score'] * 100:.0f}%")

    categories = list(CATEGORIES)
    cat_scores = result["category_scores"]
    max_job_weighted = max((cat_scores[c]["job_weighted"] for c in categories), default=1) or 1
    job_values = [cat_scores[c]["job_weighted"] / max_job_weighted for c in categories]
    resume_values = [cat_scores[c]["resume_weighted"] / max_job_weighted for c in categories]

    st.plotly_chart(build_radar_figure(categories, job_values, resume_values), use_container_width=True)

    if result["credibility_score"] is not None:
        st.subheader("Resume Credibility")
        st.metric("Credibility Score", f"{result['credibility_score']:.0f}/100")
        detail = result["credibility_detail"]
        st.caption(f"Total experience: {detail['total_experience_years']} years")
        if detail["flags"]:
            for flag in detail["flags"]:
                st.warning(f"[{flag['severity']}] {flag['kind']}: {flag['detail']}")
        else:
            st.success("No consistency flags.")
    else:
        st.caption(
            'Credibility score unavailable — this resume version hasn\'t been structured yet '
            '("Resumes" page → "Parse structure").'
        )

    st.subheader(f"Gap List ({len(result['gap_list'])})")
    if not result["gap_list"]:
        st.success("No gaps — every requirement is covered by a confident keyword match.")
    for gap in result["gap_list"]:
        badge_color = REQ_TYPE_COLORS[gap["req_type"]]
        status_label = "Weak match" if gap["status"] == "weak_match" else "Missing"
        st.markdown(
            f"<span style='color:{badge_color}; font-weight:600; font-size:0.8em;'>{REQ_TYPE_LABELS[gap['req_type']]}</span> "
            f"· **{status_label}** · [{gap['category']}] {gap['raw_text']}",
            unsafe_allow_html=True,
        )
        if gap.get("matched_phrase"):
            st.caption(f'closest resume match: "{gap["matched_phrase"]}" (similarity {gap["match_confidence"]:.2f})')
        if gap.get("source_detail"):
            st.caption(f"why this is required: {gap['source_detail']}")
