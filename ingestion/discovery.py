import re
from dataclasses import dataclass
from typing import Protocol

import requests

from config import settings
from db.connection import get_conn, get_or_create

_SITE_AND_TOKEN_PATTERN = {
    "greenhouse": ("boards.greenhouse.io", re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)")),
    "lever": ("jobs.lever.co", re.compile(r"jobs\.lever\.co/([\w-]+)")),
    "ashby": ("jobs.ashbyhq.com", re.compile(r"jobs\.ashbyhq\.com/([\w-]+)")),
}


@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str


class SearchProvider(Protocol):
    def search(self, query: str) -> list[SearchResult]:
        ...


class SerperSearchProvider:
    """https://serper.dev — free tier, simple API-key auth, JSON in/out."""

    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.serper_api_key
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is not set (see .env.example)")

    def search(self, query: str) -> list[SearchResult]:
        response = requests.post(
            self.ENDPOINT,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": query},
            timeout=15,
        )
        response.raise_for_status()
        results = response.json().get("organic", [])
        return [
            SearchResult(title=r.get("title", ""), link=r.get("link", ""), snippet=r.get("snippet", ""))
            for r in results
        ]


def discover_boards(role_title: str, ats_type: str, provider: SearchProvider | None = None) -> list[str]:
    """Search for live postings of role_title on a given ATS type, extract the
    company's board token from result URLs, upsert into companies, return new tokens."""
    if ats_type not in _SITE_AND_TOKEN_PATTERN:
        raise ValueError(f"Unknown ats_type: {ats_type}")

    site, token_pattern = _SITE_AND_TOKEN_PATTERN[ats_type]
    provider = provider or SerperSearchProvider()
    query = f'site:{site} "{role_title}"'

    tokens: set[str] = set()
    for result in provider.search(query):
        match = token_pattern.search(result.link)
        if match:
            tokens.add(match.group(1))

    new_tokens = []
    with get_conn() as conn:
        for token in tokens:
            _, created = get_or_create(
                conn,
                "companies",
                {"ats_type": ats_type, "ats_board_token": token},
                {"name": token, "discovered_via": f'search:"{query}"'},
            )
            if created:
                new_tokens.append(token)

    return new_tokens
