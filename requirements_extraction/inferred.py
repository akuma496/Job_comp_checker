import logging
from typing import Mapping

from requirements_extraction.claude_client import call_claude_tool
from requirements_extraction.models import CATEGORIES, RequirementDraft, coerce_items

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You analyze a job posting's metadata and text to infer requirements that are
IMPLIED but never explicitly stated. Base each inference on concrete signals in the metadata:
seniority level, team/department context, company/industry context, location. For example, a
"Senior" role on a small team at a fintech company implies on-call rotation and
compliance-awareness even though the posting never says so.

Do NOT repeat anything already explicitly written in the posting text — only genuinely unstated
implications. If you can't confidently infer anything beyond the literal text, return an empty
list. For each inferred requirement, classify it into one of: core_skill, tool,
domain_knowledge, seniority_leadership. Give a confidence (0-1, your genuine belief this
inference is correct) and a one-sentence rationale citing exactly which signal(s) led to it."""

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
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
        }
    },
    "required": ["requirements"],
}


def infer_context_requirements(job: Mapping) -> list[RequirementDraft]:
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
        tool_name="record_inferred_requirements",
        tool_description="Record requirements implied by context but not explicitly stated in the posting.",
        input_schema=INPUT_SCHEMA,
        max_tokens=4096,
    )
    drafts = []
    for item in coerce_items(result.get("requirements", [])):
        if not isinstance(item, dict) or "raw_text" not in item or "category" not in item:
            logger.warning("skipping malformed inferred requirement item: %r", item)
            continue
        drafts.append(
            RequirementDraft(
                raw_text=item["raw_text"],
                category=item["category"],
                confidence=float(item.get("confidence", 0.5)),
                source_detail=item.get("rationale"),
            )
        )
    return drafts
