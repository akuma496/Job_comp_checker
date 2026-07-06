from ingestion.base import AtsIngestor, RawPosting, strip_html
from ingestion.http import polite_get


class AshbyIngestor(AtsIngestor):
    ats_type = "ashby"

    def fetch_postings(self, board_token: str) -> list[RawPosting]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"
        response = polite_get(url)
        if response.status_code != 200:
            return []

        postings = []
        for job in response.json().get("jobs", []):
            postings.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("title", ""),
                    raw_text=strip_html(job.get("descriptionHtml")),
                    posting_url=job.get("jobUrl"),
                    location=job.get("location"),
                    remote_flag=bool(job.get("isRemote")),
                    department=job.get("departmentName"),
                    seniority_raw=job.get("employmentType"),
                )
            )
        return postings
