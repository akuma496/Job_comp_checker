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
    the array comes back malformed in one of a few observed shapes:
    - JSON-encoded as a string instead of a real array
    - a single item dict instead of a one-item list
    - an object keyed by index (e.g. {"0": {...}, "1": {...}}) instead of an array
    - one level of extra list-nesting (e.g. [[{...}, {...}]] instead of [{...}, {...}])
    Recover each of these instead of silently iterating/dropping the data."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("requirements field was a non-JSON string, dropping: %r", raw[:200])
            return []

    if isinstance(raw, dict):
        if "raw_text" in raw:
            return [raw]
        raw = list(raw.values())

    if not isinstance(raw, list):
        logger.warning("requirements field was an unrecognized type: %r", type(raw))
        return []

    flattened = []
    for item in raw:
        if isinstance(item, list):
            flattened.extend(item)
        else:
            flattened.append(item)
    return flattened
