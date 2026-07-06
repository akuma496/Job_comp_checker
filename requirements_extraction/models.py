from dataclasses import dataclass

CATEGORIES = ("core_skill", "tool", "domain_knowledge", "seniority_leadership")


@dataclass
class RequirementDraft:
    raw_text: str
    category: str
    confidence: float = 1.0
    source_detail: str | None = None
