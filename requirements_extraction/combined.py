import logging
from typing import Mapping

from requirements_extraction.claude_client import call_claude_tool
from requirements_extraction.models import CATEGORIES, RequirementDraft, coerce_items

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You analyze a job posting and extract two DISTINCT categories of
requirements. Keep them strictly separate — do not let one category's reasoning bleed
into the other.

1. EXPLICIT requirements: things literally, explicitly stated in the POSTING TEXT only.
   Every explicit item must be traceable to an actual phrase in the posting text — never
   to the metadata fields (seniority/department/location) below, even if they seem
   relevant. Those metadata fields exist solely to support category 2; do not let them
   influence category 1 at all. Keep each raw_text short and specific (a phrase, not a
   whole sentence). Confidence should be near 1.0 for all of these since they are
   literal quotes from the text.

2. CONTEXT-INFERRED requirements: things IMPLIED by metadata (seniority level,
   team/department context, company/industry context, location) but NEVER explicitly
   stated in the text. Do NOT repeat anything already captured in the explicit list —
   only genuinely unstated implications. If you can't confidently infer anything beyond
   the literal text, return an empty list for this category. For each, give a
   confidence (0-1, your genuine belief this inference is correct) and a one-sentence
   rationale citing exactly which signal(s) led to it.

For every requirement in either category, classify it into exactly one of: core_skill
(a specific technical skill, language, or methodology), tool (a specific named tool,
platform, or framework), domain_knowledge (industry or subject-matter knowledge),
seniority_leadership (stated or implied experience level, management, or ownership
expectations)."""

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "explicit_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "confidence": {"type": "number"},
                },
                "required": ["raw_text", "category"],
            },
        },
        "context_inferred_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string", "description": "The implied requirement, phrased as a requirement"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "confidence": {"type": "number", "description": "0-1 self-rated confidence"},
                    "rationale": {"type": "string", "description": "Which metadata/context signal led to this inference"},
                },
                "required": ["raw_text", "category", "confidence", "rationale"],
            },
        },
    },
    "required": ["explicit_requirements", "context_inferred_requirements"],
}


def _drafts_from_items(items, default_confidence: float) -> list[RequirementDraft]:
    drafts = []
    for item in coerce_items(items):
        if not isinstance(item, dict) or "raw_text" not in item or "category" not in item:
            logger.warning("skipping malformed requirement item: %r", item)
            continue
        drafts.append(
            RequirementDraft(
                raw_text=item["raw_text"],
                category=item["category"],
                confidence=float(item.get("confidence", default_confidence)),
                source_detail=item.get("rationale"),
            )
        )
    return drafts


def extract_requirements(job: Mapping) -> tuple[list[RequirementDraft], list[RequirementDraft]]:
    """One Claude call producing both explicit and context-inferred requirements —
    sends the job posting text once instead of twice (see the two-call version this
    replaced in explicit.py/inferred.py, removed once this was verified)."""
    user_prompt = (
        f"Job title: {job['title']}\n"
        f"Seniority (raw): {job['seniority_raw'] or 'unknown'}\n"
        f"Department: {job['department'] or 'unknown'}\n"
        f"Location: {job['location'] or 'unknown'}\n\n"
        f"Posting text:\n{job['raw_text']}"
    )
    result = call_claude_tool(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_name="record_job_requirements",
        tool_description="Record both the explicit and context-inferred requirements found in the job posting.",
        input_schema=INPUT_SCHEMA,
        max_tokens=8192,
    )

    explicit_drafts = _drafts_from_items(result.get("explicit_requirements", []), default_confidence=1.0)
    inferred_drafts = _drafts_from_items(result.get("context_inferred_requirements", []), default_confidence=0.5)
    return explicit_drafts, inferred_drafts
