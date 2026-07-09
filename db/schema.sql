-- Job Comp Checker schema. Source of truth for the SQLite database.
-- user_id columns default to 1 (single-user today) so multi-user later is a
-- data migration, not a schema rewrite.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ats_type TEXT NOT NULL CHECK (ats_type IN ('greenhouse', 'lever', 'ashby', 'manual')),
    ats_board_token TEXT NOT NULL,
    discovered_via TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ats_type, ats_board_token)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies (id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    role_query TEXT,
    location TEXT,
    remote_flag INTEGER NOT NULL DEFAULT 0,
    seniority_raw TEXT,
    department TEXT,
    posting_url TEXT,
    raw_text TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('ats', 'manual')),
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'removed')),
    UNIQUE (company_id, external_id)
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    category TEXT
);

CREATE TABLE IF NOT EXISTS skill_aliases (
    id INTEGER PRIMARY KEY,
    alias_text TEXT NOT NULL UNIQUE,
    skill_id INTEGER NOT NULL REFERENCES skills (id)
);

CREATE TABLE IF NOT EXISTS skill_cooccurrence (
    skill_a_id INTEGER NOT NULL REFERENCES skills (id),
    skill_b_id INTEGER NOT NULL REFERENCES skills (id),
    cooccurrence_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (skill_a_id, skill_b_id),
    CHECK (skill_a_id < skill_b_id)
);

CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs (id),
    req_type TEXT NOT NULL CHECK (req_type IN ('explicit', 'context_inferred', 'cooccurring')),
    category TEXT NOT NULL CHECK (category IN ('core_skill', 'tool', 'domain_knowledge', 'seniority_leadership')),
    raw_text TEXT NOT NULL,
    normalized_skill_id INTEGER REFERENCES skills (id),
    confidence REAL NOT NULL DEFAULT 1.0,
    source_detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users (id),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY,
    resume_id INTEGER NOT NULL REFERENCES resumes (id),
    version_label TEXT NOT NULL,
    file_path TEXT,
    raw_text TEXT,
    parsed_json TEXT,
    parsed_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users (id),
    resume_version_id INTEGER NOT NULL REFERENCES resume_versions (id),
    job_id INTEGER NOT NULL REFERENCES jobs (id),
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    overall_score REAL,
    category_scores_json TEXT,
    gap_list_json TEXT,
    credibility_score REAL,
    credibility_detail_json TEXT,
    UNIQUE (resume_version_id, job_id)
);

CREATE TABLE IF NOT EXISTS onet_job_zones (
    zone INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    typical_experience_text TEXT,
    typical_education_text TEXT,
    min_years_estimate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs (company_id);
CREATE INDEX IF NOT EXISTS idx_requirements_job ON requirements (job_id);
CREATE INDEX IF NOT EXISTS idx_requirements_skill ON requirements (normalized_skill_id);
CREATE INDEX IF NOT EXISTS idx_matches_job ON matches (job_id);
