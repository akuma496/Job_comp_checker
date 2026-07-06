from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawPosting:
    external_id: str
    title: str
    raw_text: str
    posting_url: str | None = None
    location: str | None = None
    remote_flag: bool = False
    department: str | None = None
    seniority_raw: str | None = None


class AtsIngestor(ABC):
    """One implementation per ATS type. Each knows only how to turn a board
    token into a list of RawPosting — upserting into the DB is the pipeline's job."""

    ats_type: str

    @abstractmethod
    def fetch_postings(self, board_token: str) -> list[RawPosting]:
        ...
