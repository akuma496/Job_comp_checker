import json
import re
from pathlib import Path

import streamlit as st

from config import BASE_DIR
from db.connection import get_conn
from resume.parser import extract_raw_text, parsed_resume_to_json, structure_resume

RESUME_DIR = BASE_DIR / "data" / "resumes"

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_path_component(value: str, fallback: str = "file") -> str:
    """Neutralize path separators and '..' so this can't escape RESUME_DIR when
    concatenated into a filename (value may come straight from user text_input
    or an uploaded file's client-supplied name)."""
    value = _UNSAFE_CHARS.sub("_", value).lstrip(".")
    return value or fallback


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
                   resume_versions.file_path, resume_versions.raw_text, resume_versions.parsed_json,
                   resume_versions.parsed_at
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
            "Resume", options=["<new resume>"] + existing_names, help="Pick an existing resume to add version(s) to, or create a new one."
        )
        new_name = st.text_input("New resume name", disabled=name_choice != "<new resume>", placeholder='e.g. "backend-focused"')
        version_label = st.text_input(
            "Version label",
            placeholder='e.g. "v1"',
            help="Only used when uploading a single file. For multiple files, each version label is derived from its filename.",
        )
        uploaded_files = st.file_uploader("Resume file(s)", type=["pdf", "docx", "txt"], accept_multiple_files=True)
        submitted = st.form_submit_button("Add resume version(s)")

    if submitted:
        display_name = new_name.strip() if name_choice == "<new resume>" else name_choice
        if not display_name:
            st.error("Give the resume a name.")
        elif not uploaded_files:
            st.error("Choose at least one file to upload.")
        elif len(uploaded_files) == 1 and not version_label.strip():
            st.error("Give this version a label.")
        else:
            RESUME_DIR.mkdir(parents=True, exist_ok=True)
            used_labels: set[str] = set()
            added = []
            for uploaded_file in uploaded_files:
                if len(uploaded_files) == 1:
                    label = version_label.strip()
                else:
                    label = Path(uploaded_file.name).stem
                    original_label = label
                    suffix = 2
                    while label in used_labels:
                        label = f"{original_label}_{suffix}"
                        suffix += 1
                used_labels.add(label)

                safe_display_name = _safe_path_component(display_name)
                safe_label = _safe_path_component(label)
                safe_upload_name = _safe_path_component(Path(uploaded_file.name).name)
                dest_path = RESUME_DIR / f"{safe_display_name}_{safe_label}_{safe_upload_name}"
                dest_path.write_bytes(uploaded_file.getvalue())

                try:
                    raw_text = extract_raw_text(dest_path)
                except ValueError as exc:
                    st.error(f"{uploaded_file.name}: {exc}")
                    continue

                with get_conn() as conn:
                    resume_id = _get_or_create_resume(conn, display_name)
                    conn.execute(
                        """
                        INSERT INTO resume_versions (resume_id, version_label, file_path, raw_text)
                        VALUES (?, ?, ?, ?)
                        """,
                        (resume_id, label, str(dest_path), raw_text),
                    )
                added.append((label, len(raw_text)))

            if added:
                summary = ", ".join(f'"{label}" ({chars} chars)' for label, chars in added)
                st.success(f'Added to "{display_name}": {summary}')
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

            if version["parsed_json"]:
                st.success(f"Structured (parsed {version['parsed_at']})")
                data = json.loads(version["parsed_json"])
                st.write(f"**Experience** ({len(data['experience'])})")
                for exp in data["experience"]:
                    end = exp["end_date"] or "present"
                    st.write(f"- {exp['title']} @ {exp['company']} ({exp['start_date']} → {end})")
                    for bullet in exp["bullets"]:
                        st.caption(f"　· {bullet}")
                st.write(f"**Education** ({len(data['education'])})")
                for edu in data["education"]:
                    st.write(f"- {edu['degree']}, {edu['institution']}")
                st.write(f"**Skills claimed**: {', '.join(data['skills_claimed'])}")
            else:
                if st.button("Parse structure (uses 1 Claude call)", key=f"parse_{version['id']}"):
                    with st.spinner("Structuring resume..."):
                        try:
                            parsed = structure_resume(version["raw_text"])
                            parsed_json = parsed_resume_to_json(parsed)
                            with get_conn() as conn:
                                conn.execute(
                                    "UPDATE resume_versions SET parsed_json = ?, parsed_at = datetime('now') WHERE id = ?",
                                    (parsed_json, version["id"]),
                                )
                        except Exception as exc:
                            st.error(f"Structuring failed: {exc}")
                        else:
                            st.rerun()

            st.divider()
            preview = (version["raw_text"] or "")[:2000]
            st.text(preview + ("..." if len(version["raw_text"] or "") > 2000 else ""))
