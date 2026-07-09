import pandas as pd
import streamlit as st

from dashboard.charts import REQ_TYPE_COLORS, REQ_TYPE_LABELS, build_requirement_count_bar
from db.connection import get_conn
from requirements_extraction.pipeline import process_job

REQ_TYPE_ORDER = ["explicit", "context_inferred", "cooccurring"]


def _load_jobs_df() -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT jobs.id, companies.name AS company, jobs.title, jobs.location,
                   jobs.source_type, jobs.status, jobs.last_seen_at
            FROM jobs JOIN companies ON companies.id = jobs.company_id
            ORDER BY jobs.last_seen_at DESC
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def _load_job_detail(job_id: int) -> dict:
    with get_conn() as conn:
        job = conn.execute(
            """
            SELECT jobs.*, companies.name AS company_name FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
        reqs = conn.execute(
            "SELECT req_type, category, raw_text, confidence, source_detail FROM requirements WHERE job_id = ? ORDER BY confidence DESC",
            (job_id,),
        ).fetchall()
    return {"job": dict(job), "requirements": [dict(r) for r in reqs]}


_BORDER_STYLE = {"explicit": "solid", "context_inferred": "dashed", "cooccurring": "dotted"}


def _badge(req_type: str) -> str:
    color = REQ_TYPE_COLORS[req_type]
    border = _BORDER_STYLE[req_type]
    return (
        f'<span style="color:{color}; border:1.5px {border} {color}; '
        f'border-radius:4px; padding:1px 6px; font-size:0.75em; font-weight:600;">'
        f"{REQ_TYPE_LABELS[req_type]}</span>"
    )


def render() -> None:
    st.header("Jobs & Requirements Browser")
    st.caption(
        "Browse jobs ingested so far (Milestone 1) and their explicit / context-inferred / "
        "co-occurring requirements (Milestone 2). Match/gap scoring against a resume arrives "
        "in a later milestone."
    )

    df = _load_jobs_df()
    if df.empty:
        st.info("No jobs ingested yet. Run `scripts/run_ingestion.py --role \"...\"` first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        company_filter = st.multiselect("Company", sorted(df["company"].unique()))
    with col2:
        status_filter = st.multiselect("Status", sorted(df["status"].unique()), default=["active"])

    filtered = df
    if company_filter:
        filtered = filtered[filtered["company"].isin(company_filter)]
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]

    st.write(f"{len(filtered)} job(s)")

    selection = st.dataframe(
        filtered,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        column_order=["id", "company", "title", "location", "source_type", "status", "last_seen_at"],
    )

    selected_rows = selection.selection.rows if selection and selection.selection else []
    if not selected_rows:
        st.info("Select a row above to see its extracted requirements.")
        return

    job_id = int(filtered.iloc[selected_rows[0]]["id"])
    detail = _load_job_detail(job_id)
    job = detail["job"]

    st.subheader(f"{job['title']} — {job['company_name']}")
    meta_cols = st.columns(4)
    meta_cols[0].metric("Location", job["location"] or "—")
    meta_cols[1].metric("Department", job["department"] or "—")
    meta_cols[2].metric("Source", job["source_type"])
    meta_cols[3].metric("Status", job["status"])
    if job["posting_url"]:
        st.markdown(f"[View original posting]({job['posting_url']})")

    if st.button("Re-extract this job", key=f"reextract_{job_id}", help="Costs 2 Claude API calls"):
        with st.spinner("Extracting requirements..."):
            process_job(job_id)
        st.rerun()

    reqs_by_type: dict[str, list[dict]] = {t: [] for t in REQ_TYPE_ORDER}
    for r in detail["requirements"]:
        reqs_by_type.setdefault(r["req_type"], []).append(r)

    counts = {t: len(reqs_by_type.get(t, [])) for t in REQ_TYPE_ORDER}
    if sum(counts.values()) == 0:
        st.warning("This job hasn't been through requirement extraction yet (Milestone 2).")
        return

    st.plotly_chart(build_requirement_count_bar(counts), use_container_width=True)

    for req_type in REQ_TYPE_ORDER:
        items = reqs_by_type.get(req_type, [])
        with st.expander(f"{REQ_TYPE_LABELS[req_type]} ({len(items)})", expanded=(req_type == "explicit")):
            if not items:
                st.write("(none)")
                continue
            for item in items:
                st.markdown(
                    f"{_badge(req_type)} **[{item['category']}]** {item['raw_text']} "
                    f"&nbsp;·&nbsp; confidence {item['confidence']:.2f}",
                    unsafe_allow_html=True,
                )
                if item["source_detail"]:
                    st.caption(f"why: {item['source_detail']}")
