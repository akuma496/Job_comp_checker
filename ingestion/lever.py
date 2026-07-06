from ingestion.base import AtsIngestor, RawPosting, strip_html
from ingestion.http import polite_get


class LeverIngestor(AtsIngestor):
    ats_type = "lever"

    def fetch_postings(self, board_token: str) -> list[RawPosting]:
        url = f"https://api.lever.co/v0/postings/{board_token}?mode=json"
        response = polite_get(url)
        if response.status_code != 200:
            return []

        postings = []
        for job in response.json():
            categories = job.get("categories", {})
            sections = [strip_html(job.get("descriptionPlain") or job.get("description"))]
            for section in job.get("lists", []):
                sections.append(f"{section.get('text', '')}\n{strip_html(section.get('content'))}")
            postings.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("text", ""),
                    raw_text="\n\n".join(s for s in sections if s),
                    posting_url=job.get("hostedUrl"),
                    location=categories.get("location"),
                    remote_flag=job.get("workplaceType") == "remote",
                    department=categories.get("team"),
                    seniority_raw=categories.get("commitment"),
                )
            )
        return postings
