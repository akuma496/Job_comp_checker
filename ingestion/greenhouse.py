from ingestion.base import AtsIngestor, RawPosting, strip_html
from ingestion.http import polite_get


class GreenhouseIngestor(AtsIngestor):
    ats_type = "greenhouse"

    def fetch_postings(self, board_token: str) -> list[RawPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        response = polite_get(url)
        if response.status_code != 200:
            return []

        postings = []
        for job in response.json().get("jobs", []):
            postings.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("title", ""),
                    raw_text=strip_html(job.get("content")),
                    posting_url=job.get("absolute_url"),
                    location=(job.get("location") or {}).get("name"),
                    department=", ".join(
                        d.get("name", "") for d in job.get("departments", [])
                    )
                    or None,
                )
            )
        return postings
