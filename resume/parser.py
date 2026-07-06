from pathlib import Path

import pdfplumber
from docx import Document


def extract_raw_text(path: str | Path) -> str:
    """Pull raw text out of a resume file. No structuring yet (experience entries,
    dates, skills) — that lands with the matching engine in Milestone 3, since it
    needs a Claude call and is only worth doing once we can actually match against jobs."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    elif suffix == ".docx":
        document = Document(path)
        return "\n".join(p.text for p in document.paragraphs).strip()
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8").strip()
    else:
        raise ValueError(f"Unsupported resume file type: {suffix}")
