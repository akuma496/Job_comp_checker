import logging
from typing import Mapping

from requirements_extraction.claude_client import call_claude_tool
from requirements_extraction.models import CATEGORIES, RequirementDraft, coerce_items

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract requirements from job postings. Extract ONLY requirements that
are literally, explicitly stated in the posting text below — do not infer, guess, or add
anything the text doesn't say. For each requirement, classify it into exactly one category:
- core_skill: a specific technical skill, language, or methodology
- tool: a specific named tool, platform, or framework
- domain_knowledge: industry or subject-matter knowledge
- seniority_leadership: stated experience level, management, or ownership expectations

Keep each raw_text short and specific (a phrase, not a whole sentence). Confidence should be
near 1.0 for all of these since they are literal quotes from the text."""

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
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
        }
    },
    "required": ["requirements"],
}


def extract_explicit_requirements(job: Mapping) -> list[RequirementDraft]:
    user_prompt = f"Job title: {job['title']}\n\nPosting text:\n{job['raw_text']}"
    result = call_claude_tool(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_name="record_requirements",
        tool_description="Record the explicit requirements found in the job posting.",
        input_schema=INPUT_SCHEMA,
    )
    drafts = []
    for item in coerce_items(result.get("requirements", [])):
        if not isinstance(item, dict) or "raw_text" not in item or "category" not in item:
            logger.warning("skipping malformed explicit requirement item: %r", item)
            continue
        drafts.append(
            RequirementDraft(
                raw_text=item["raw_text"],
                category=item["category"],
                confidence=float(item.get("confidence", 1.0)),
            )
        )
    return drafts
