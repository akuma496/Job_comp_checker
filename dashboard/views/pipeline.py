import streamlit as st

from db.connection import get_conn
from ingestion.pipeline import run_pipeline
from requirements_extraction.cooccurrence import recompute_cooccurrence_matrix
from requirements_extraction.pipeline import finalize_cooccurrence_for_batch, process_job
from resume.taxonomy import backfill_normalized_skills, load_seed_taxonomy


def _incomplete_job_ids() -> list[int]:
    """Jobs never processed, or processed but with 0 explicit requirements
    (the signature of the max-tokens-truncation bug from before the fix)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT jobs.id FROM jobs
            WHERE jobs.status = 'active' AND jobs.id NOT IN (
                SELECT job_id FROM requirements WHERE req_type = 'explicit'
            )
            """
        ).fetchall()
    return [r["id"] for r in rows]


def render() -> None:
    st.header("Pipeline Controls")
    st.caption("Trigger ingestion and requirement extraction without leaving the browser.")

    st.subheader("1. Pull jobs (Serper.dev search + ATS boards)")
    st.caption("Costs Serper.dev search queries — a handful per run, not per job.")
    role_title = st.text_input("Role title", value="AI Engineer")
    if st.button("Run Ingestion"):
        with st.spinner(f'Searching and pulling postings for "{role_title}"...'):
            stats = run_pipeline(role_title)
        st.success(
            f"New companies discovered: {stats['new_companies']} · "
            f"Postings seen: {stats['jobs_seen']} · "
            f"Postings matching '{role_title}': {stats['jobs_matched']}"
        )

    st.divider()

    st.subheader("2. Extract requirements")
    st.caption("Costs Anthropic API credit — one Claude call per job processed.")
    incomplete_ids = _incomplete_job_ids()
    st.write(f"Jobs needing extraction (never processed, or missing explicit requirements): **{len(incomplete_ids)}**")

    if incomplete_ids and st.button(f"Re-extract all {len(incomplete_ids)} incomplete job(s)"):
        progress = st.progress(0.0)
        status = st.empty()
        results = []
        succeeded_ids = []
        for i, job_id in enumerate(incomplete_ids):
            status.write(f"Processing job {job_id} ({i + 1}/{len(incomplete_ids)})...")
            try:
                stats = process_job(job_id, recompute_cooccurrence=False)
                results.append((job_id, stats, None))
                succeeded_ids.append(job_id)
            except Exception as exc:
                results.append((job_id, None, str(exc)))
            progress.progress((i + 1) / len(incomplete_ids))

        status.write("Finalizing co-occurrence matrix...")
        finalize_cooccurrence_for_batch(succeeded_ids)
        status.empty()

        succeeded = [r for r in results if r[2] is None]
        failed = [r for r in results if r[2] is not None]
        st.success(f"Processed {len(succeeded)} job(s) successfully.")
        if failed:
            st.error(f"{len(failed)} job(s) failed:")
            for job_id, _, error in failed:
                st.write(f"- job {job_id}: {error}")
        st.rerun()

    st.divider()

    st.subheader("3. Load / refresh skills taxonomy")
    st.caption(
        "Seeds the curated skills list (data/reference/skills_seed.csv) and re-normalizes "
        "existing requirements against it. Local only — no API cost. Safe to re-run any "
        "time, e.g. after editing the seed CSV."
    )
    if st.button("Load taxonomy & backfill"):
        with st.spinner("Loading taxonomy and backfilling..."):
            load_seed_taxonomy()
            updated = backfill_normalized_skills()
            recompute_cooccurrence_matrix()
        st.success(f"Taxonomy loaded; {updated} requirement(s) re-normalized.")
