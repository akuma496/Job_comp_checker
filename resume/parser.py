import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber
from docx import Document

from requirements_extraction.claude_client import call_claude_tool
from requirements_extraction.models import coerce_items

logger = logging.getLogger(__name__)


def extract_raw_text(path: str | Path) -> str:
    """Pull raw text out of a resume file."""
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


@dataclass
class ExperienceEntry:
    title: str
    company: str
    start_date: date | None
    end_date: date | None  # None means "present" / ongoing
    bullets: list[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    degree: str
    institution: str
    field_of_study: str | None = None
    graduation_date: date | None = None


@dataclass
class ParsedResume:
    experience: list[ExperienceEntry]
    education: list[EducationEntry]
    skills_claimed: list[str]


STRUCTURE_SYSTEM_PROMPT = """You convert a resume's raw text into structured data. Extract every
work experience entry (title, company, start date, end date, bullet points), every education
entry (degree, institution, field of study, graduation date), and a flat list of skills the
person explicitly claims (from a skills section or clearly stated proficiencies).

Dates: use "YYYY-MM" format when a month is known, "YYYY" if only the year is known, and null
for an end_date that means the role is current/ongoing (e.g. "Present"). Do not guess a date
that isn't stated or clearly implied."""

STRUCTURE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "company"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree": {"type": "string"},
                    "institution": {"type": "string"},
                    "field_of_study": {"type": ["string", "null"]},
                    "graduation_date": {"type": ["string", "null"]},
                },
                "required": ["degree", "institution"],
            },
        },
        "skills_claimed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["experience", "education", "skills_claimed"],
}


def _parse_partial_date(value: str | None) -> date | None:
    if not value:
        return None
    parts = value.strip().split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        return date(year, month, 1)
    except (ValueError, IndexError):
        logger.warning("could not parse date %r, treating as unknown", value)
        return None


def structure_resume(raw_text: str) -> ParsedResume:
    """One Claude call per resume version — infrequent (per-upload, not per-match),
    so the cost is negligible compared to per-job requirement extraction."""
    result = call_claude_tool(
        system_prompt=STRUCTURE_SYSTEM_PROMPT,
        user_prompt=f"Resume text:\n{raw_text}",
        tool_name="record_resume_structure",
        tool_description="Record the structured experience, education, and claimed skills from this resume.",
        input_schema=STRUCTURE_INPUT_SCHEMA,
        max_tokens=4096,
    )

    experience = []
    for item in coerce_items(result.get("experience", [])):
        if not isinstance(item, dict) or "title" not in item or "company" not in item:
            logger.warning("skipping malformed experience item: %r", item)
            continue
        experience.append(
            ExperienceEntry(
                title=item["title"],
                company=item["company"],
                start_date=_parse_partial_date(item.get("start_date")),
                end_date=_parse_partial_date(item.get("end_date")),
                bullets=[b for b in item.get("bullets", []) if isinstance(b, str)],
            )
        )

    education = []
    for item in coerce_items(result.get("education", [])):
        if not isinstance(item, dict) or "degree" not in item or "institution" not in item:
            logger.warning("skipping malformed education item: %r", item)
            continue
        education.append(
            EducationEntry(
                degree=item["degree"],
                institution=item["institution"],
                field_of_study=item.get("field_of_study"),
                graduation_date=_parse_partial_date(item.get("graduation_date")),
            )
        )

    skills_claimed = [s for s in coerce_items(result.get("skills_claimed", [])) if isinstance(s, str)]

    return ParsedResume(experience=experience, education=education, skills_claimed=skills_claimed)


def parsed_resume_to_json(parsed: ParsedResume) -> str:
    return json.dumps(asdict(parsed), default=lambda v: v.isoformat() if isinstance(v, date) else str(v))


def parsed_resume_from_json(raw_json: str) -> ParsedResume:
    data = json.loads(raw_json)
    return ParsedResume(
        experience=[
            ExperienceEntry(
                title=e["title"],
                company=e["company"],
                start_date=date.fromisoformat(e["start_date"]) if e["start_date"] else None,
                end_date=date.fromisoformat(e["end_date"]) if e["end_date"] else None,
                bullets=e["bullets"],
            )
            for e in data["experience"]
        ],
        education=[
            EducationEntry(
                degree=e["degree"],
                institution=e["institution"],
                field_of_study=e.get("field_of_study"),
                graduation_date=date.fromisoformat(e["graduation_date"]) if e["graduation_date"] else None,
            )
            for e in data["education"]
        ],
        skills_claimed=data["skills_claimed"],
    )
