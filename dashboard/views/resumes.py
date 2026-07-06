from pathlib import Path

import streamlit as st

from config import BASE_DIR
from db.connection import get_conn
from resume.parser import extract_raw_text

RESUME_DIR = BASE_DIR / "data" / "resumes"


def _get_or_create_resume(conn, display_name: str) -> int:
    row = conn.execute("SELECT id FROM resumes WHERE display_name = ?", (display_name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO resumes (display_name) VALUES (?)", (display_name,))
    return cursor.lastrowid


def _load_resumes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT resume_versions.id, resumes.display_name, resume_versions.version_label,
                   resume_versions.file_path, resume_versions.raw_text, resume_versions.parsed_at
            FROM resume_versions JOIN resumes ON resumes.id = resume_versions.resume_id
            ORDER BY resume_versions.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def render() -> None:
    st.header("Resumes")
    st.caption(
        "Upload a resume file per tailored version (e.g. \"backend-focused\", \"data-focused\"). "
        "Raw text is extracted now; structured parsing (experience entries, dates, skills) and "
        "matching against jobs arrive with the matching engine."
    )

    existing_names = sorted({r["display_name"] for r in _load_resumes()})

    with st.form("upload_resume_form", clear_on_submit=True):
        name_choice = st.selectbox(
            "Resume", options=["<new resume>"] + existing_names, help="Pick an existing resume to add a new version to, or create a new one."
        )
        new_name = st.text_input("New resume name", disabled=name_choice != "<new resume>", placeholder='e.g. "backend-focused"')
        version_label = st.text_input("Version label", placeholder='e.g. "v1"')
        uploaded_file = st.file_uploader("Resume file", type=["pdf", "docx", "txt"])
        submitted = st.form_submit_button("Add resume version")

    if submitted:
        display_name = new_name.strip() if name_choice == "<new resume>" else name_choice
        if not display_name:
            st.error("Give the resume a name.")
        elif not version_label.strip():
            st.error("Give this version a label.")
        elif uploaded_file is None:
            st.error("Choose a file to upload.")
        else:
            RESUME_DIR.mkdir(parents=True, exist_ok=True)
            dest_path = RESUME_DIR / f"{display_name}_{version_label}_{uploaded_file.name}"
            dest_path.write_bytes(uploaded_file.getvalue())

            try:
                raw_text = extract_raw_text(dest_path)
            except ValueError as exc:
                st.error(str(exc))
                raw_text = None

            if raw_text is not None:
                with get_conn() as conn:
                    resume_id = _get_or_create_resume(conn, display_name)
                    conn.execute(
                        """
                        INSERT INTO resume_versions (resume_id, version_label, file_path, raw_text)
                        VALUES (?, ?, ?, ?)
                        """,
                        (resume_id, version_label.strip(), str(dest_path), raw_text),
                    )
                st.success(f'Added "{display_name}" / "{version_label}" ({len(raw_text)} characters extracted).')
                st.rerun()

    st.divider()
    st.subheader("Uploaded resume versions")
    versions = _load_resumes()
    if not versions:
        st.info("No resumes uploaded yet.")
        return

    for version in versions:
        with st.expander(f"{version['display_name']} — {version['version_label']}"):
            st.caption(Path(version["file_path"]).name)
            preview = (version["raw_text"] or "")[:2000]
            st.text(preview + ("..." if len(version["raw_text"] or "") > 2000 else ""))
