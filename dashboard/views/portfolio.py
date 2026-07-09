import json
from collections import Counter

import streamlit as st

from dashboard.charts import build_gap_bar_figure, build_heatmap_figure
from db.connection import get_conn
from matching.engine import compute_match
from requirements_extraction.models import CATEGORIES

TOP_N_GAPS = 15


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


def _active_job_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE status = 'active'").fetchall()
    return [r["id"] for r in rows]


def _matched_job_ids(resume_version_id: int) -> set[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT job_id FROM matches WHERE resume_version_id = ?", (resume_version_id,)
        ).fetchall()
    return {r["job_id"] for r in rows}


def _load_matches_with_jobs(resume_version_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT matches.*, jobs.title, companies.name AS company
            FROM matches
            JOIN jobs ON jobs.id = matches.job_id
            JOIN companies ON companies.id = jobs.company_id
            WHERE matches.resume_version_id = ? AND jobs.status = 'active'
            ORDER BY matches.overall_score ASC
            """,
            (resume_version_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def render() -> None:
    st.header("Portfolio")
    st.caption("Match/gap patterns across every job you're tracking, for one resume version. No application-status tracking here — that's out of scope.")

    resume_versions = _load_resume_versions()
    if not resume_versions:
        st.info('No resumes uploaded yet. Add one on the "Resumes" page.')
        return

    resume_options = {f"{r['display_name']} / {r['version_label']} (#{r['id']})": r["id"] for r in resume_versions}
    resume_label = st.selectbox("Resume version", list(resume_options.keys()))
    resume_version_id = resume_options[resume_label]

    active_ids = set(_active_job_ids())
    missing_ids = active_ids - _matched_job_ids(resume_version_id)

    if missing_ids and st.button(f"Compute matches for {len(missing_ids)} job(s) missing one (local, no API cost)"):
        progress = st.progress(0.0)
        status = st.empty()
        for i, job_id in enumerate(sorted(missing_ids)):
            status.write(f"Matching job {job_id} ({i + 1}/{len(missing_ids)})...")
            try:
                compute_match(resume_version_id, job_id)
            except Exception as exc:
                st.warning(f"job {job_id} failed: {exc}")
            progress.progress((i + 1) / len(missing_ids))
        status.empty()
        st.rerun()

    matches = _load_matches_with_jobs(resume_version_id)
    if not matches:
        st.info("No matches computed yet for this resume version.")
        return

    st.write(f"{len(matches)} job(s) matched")

    categories = list(CATEGORIES)
    row_labels = []
    heatmap_z = []
    gap_counter: Counter[str] = Counter()

    for m in matches:
        row_labels.append(f"{m['title']} — {m['company']}")
        cat_scores = json.loads(m["category_scores_json"])
        row = []
        for cat in categories:
            job_w = cat_scores[cat]["job_weighted"]
            resume_w = cat_scores[cat]["resume_weighted"]
            row.append((resume_w / job_w) if job_w > 0 else None)
        heatmap_z.append(row)

        gap_list = json.loads(m["gap_list_json"])
        for gap in gap_list:
            if gap["status"] == "missing":
                gap_counter[gap["raw_text"]] += 1

    st.subheader("Coverage Heatmap")
    st.plotly_chart(build_heatmap_figure(row_labels, categories, heatmap_z), use_container_width=True)

    st.subheader(f"Most Frequent Gaps (top {TOP_N_GAPS})")
    if gap_counter:
        top_gaps = gap_counter.most_common(TOP_N_GAPS)
        labels = [g[0] for g in top_gaps]
        counts = [g[1] for g in top_gaps]
        st.plotly_chart(build_gap_bar_figure(labels, counts), use_container_width=True)
    else:
        st.success("No missing requirements across any tracked job — nothing to show.")
