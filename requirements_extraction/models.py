import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CATEGORIES = ("core_skill", "tool", "domain_knowledge", "seniority_leadership")


@dataclass
class RequirementDraft:
    raw_text: str
    category: str
    confidence: float = 1.0
    source_detail: str | None = None


def coerce_items(raw) -> list:
    """Claude's tool-use output is usually a proper list of dicts, but occasionally
    returns the array JSON-encoded as a string instead. Recover that case instead of
    silently iterating it character-by-character."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("requirements field was a non-JSON string, dropping: %r", raw[:200])
            return []
    if not isinstance(raw, list):
        logger.warning("requirements field was not a list: %r", type(raw))
        return []
    return raw
