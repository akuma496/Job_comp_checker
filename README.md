# Job Comp Checker

A personal tool that pulls real job postings, figures out what each one actually
requires — including the parts nobody wrote down — and compares that against your
resume(s) to show match/gap visually.

For any job posting it tracks, it splits requirements into three signal types:

- **Explicit** — literally stated in the posting text
- **Context-inferred** — implied by seniority/team size/industry/location signals but
  never written (e.g. a "Senior" role on an 8-person healthcare team implies HIPAA
  awareness even if compliance is never mentioned)
- **Co-occurring** — skills that statistically travel together across the corpus of
  postings ingested so far (e.g. Kubernetes implying Docker/CI-CD)

Matching is a hybrid of exact keyword/taxonomy hits and local sentence-embedding
similarity for paraphrases, plus a resume credibility check (timeline consistency,
seniority-vs-experience plausibility backed by O*NET occupational data, buzzword
density, unsupported skill claims). Everything is diagnosis-only — no auto-rewrites,
no application-lifecycle tracking.

Runs entirely local (Windows), Python end-to-end, SQLite for storage.

## Setup

1. Create and activate a virtual environment, then install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e .
   ```
2. Copy `.env.example` to `.env` and fill in:
   - `ANTHROPIC_API_KEY` — used for requirement extraction and resume structuring
   - `SERPER_API_KEY` — used to discover company ATS boards (Greenhouse/Lever/Ashby)
3. One-time: seed the skills taxonomy and download the O*NET reference data:
   ```powershell
   python scripts/load_taxonomy.py
   python scripts/fetch_reference_data.py
   python scripts/build_reference_stats.py
   ```

## Running

```powershell
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501` with five pages:

- **Single Job Match** — pick a job + resume version → match score, radar chart
  (job requirements vs. resume coverage by category), ranked gap list, credibility
  report
- **Portfolio** — every tracked job ranked by fit ("Best Matches"), a coverage
  heatmap, and a "most frequent gaps" chart across everything you're tracking
- **Jobs Browser** — browse/filter ingested jobs, inspect their explicit /
  context-inferred / co-occurring requirements, re-extract individually
- **Resumes** — upload PDF/DOCX/TXT (multiple at once), parse into structured data
- **Pipeline Controls** — pull new jobs, bulk re-extract, reload the skills taxonomy

Everything is idempotent and safe to re-run.

### CLI equivalents

```powershell
python scripts/run_ingestion.py --role "AI Engineer"      # pull jobs (costs Serper queries)
python scripts/run_extraction.py --all                    # extract requirements (costs Anthropic credit)
python scripts/paste_job.py --company "Acme" --title "AI Engineer" --file posting.txt
python scripts/list_jobs.py
python scripts/show_requirements.py --job-id 49
python scripts/load_taxonomy.py                            # local only, no API cost
```

## Project structure

```
ingestion/               ATS scrapers (Greenhouse/Lever/Ashby), board discovery via Serper.dev, manual paste
requirements_extraction/ Claude-based requirement extraction (explicit + context-inferred in one call), co-occurrence matrix
resume/                  Resume parsing (Claude), skills taxonomy/normalization, credibility scoring
matching/                Local embedding model + hybrid keyword/embedding matching engine
dashboard/               Streamlit app and views
db/                      SQLite schema, connection helper, shared queries
scripts/                 CLI entry points
data/reference/          Skills taxonomy seed CSV, O*NET reference data (gitignored)
```
