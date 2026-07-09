import json
from collections import Counter

import pandas as pd
import streamlit as st

from dashboard.charts import build_gap_bar_figure, build_heatmap_figure
from db.connection import get_conn
from db.queries import load_resume_versions
from matching.engine import compute_match_batch
from requirements_extraction.models import CATEGORIES

TOP_N_GAPS = 15


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
            SELECT matches.*, jobs.title, jobs.posting_url, companies.name AS company
            FROM matches
            JOIN jobs ON jobs.id = matches.job_id
            JOIN companies ON companies.id = jobs.company_id
            WHERE matches.resume_version_id = ? AND jobs.status = 'active'
            ORDER BY matches.overall_score DESC
            """,
            (resume_version_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def render() -> None:
    st.header("Portfolio")
    st.caption("Match/gap patterns across every job you're tracking, for one resume version. No application-status tracking here — that's out of scope.")

    resume_versions = load_resume_versions()
    if not resume_versions:
        st.info('No resumes uploaded yet. Add one on the "Resumes" page.')
        return

    resume_options = {f"{r['display_name']} / {r['version_label']} (#{r['id']})": r["id"] for r in resume_versions}
    resume_label = st.selectbox("Resume version", list(resume_options.keys()))
    resume_version_id = resume_options[resume_label]

    active_ids = set(_active_job_ids())
    missing_ids = active_ids - _matched_job_ids(resume_version_id)

    def _run_matches(job_ids: list[int]) -> None:
        progress = st.progress(0.0)
        status = st.empty()

        def _on_progress(i: int, total: int, job_id: int) -> None:
            status.write(f"Matching job {job_id} ({i + 1}/{total})...")
            progress.progress((i + 1) / total)

        results = compute_match_batch(resume_version_id, job_ids, progress_callback=_on_progress)
        status.empty()

        for job_id, result in results.items():
            if isinstance(result, Exception):
                st.warning(f"job {job_id} failed: {result}")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if missing_ids and st.button(f"Compute matches for {len(missing_ids)} job(s) missing one (local, no API cost)"):
            _run_matches(sorted(missing_ids))
    with col2:
        if active_ids and st.button(
            f"Recompute ALL {len(active_ids)} matches (local, no API cost)",
            help="Force-redo every match, not just missing ones — useful after tuning changes (thresholds, taxonomy, etc.)",
        ):
            _run_matches(sorted(active_ids))

    matches = _load_matches_with_jobs(resume_version_id)
    if not matches:
        st.info("No matches computed yet for this resume version.")
        return

    st.write(f"{len(matches)} job(s) matched")

    st.subheader("Best Matches")
    st.caption("Every tracked job, ranked by overall match score for this resume version — highest first.")
    best_matches_df = pd.DataFrame(
        [
            {
                "Rank": i + 1,
                "Job": m["title"],
                "Company": m["company"],
                "Match %": round(m["overall_score"] * 100) if m["overall_score"] is not None else None,
                "Posting": m["posting_url"],
            }
            for i, m in enumerate(matches)
        ]
    )
    selection = st.dataframe(
        best_matches_df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Posting": st.column_config.LinkColumn(display_text="View"),
            "Match %": st.column_config.NumberColumn(help="Blank means this job hasn't been through requirement extraction yet"),
        },
    )

    selected_rows = selection.selection.rows if selection and selection.selection else []
    if selected_rows:
        selected_match = matches[selected_rows[0]]
        if st.button(f"View full match: {selected_match['title']} — {selected_match['company']}"):
            st.session_state["_jump_to_job_id"] = selected_match["job_id"]
            st.session_state["_jump_to_resume_version_id"] = resume_version_id
            st.session_state["nav_view"] = "Single Job Match"
            st.rerun()
    else:
        st.caption("Select a row above to jump to its full Single Job Match view (radar chart + gap list).")

    categories = list(CATEGORIES)
    gap_counter: Counter[str] = Counter()

    for m in matches:
        gap_list = json.loads(m["gap_list_json"])
        for gap in gap_list:
            if gap["status"] == "missing":
                gap_counter[gap["raw_text"]] += 1

    # Independent of the Best Matches table's best-first order — the heatmap sorts
    # worst-first so weak spots are visible without scrolling, since these two views
    # share the same underlying `matches` query but serve different reading orders.
    heatmap_matches = sorted(matches, key=lambda m: m["overall_score"] if m["overall_score"] is not None else -1)
    row_labels = []
    heatmap_z = []
    for m in heatmap_matches:
        row_labels.append(f"{m['title']} — {m['company']}")
        cat_scores = json.loads(m["category_scores_json"])
        row = []
        for cat in categories:
            job_w = cat_scores[cat]["job_weighted"]
            resume_w = cat_scores[cat]["resume_weighted"]
            row.append((resume_w / job_w) if job_w > 0 else None)
        heatmap_z.append(row)

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
