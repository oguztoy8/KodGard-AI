CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS commits (
    id BIGSERIAL PRIMARY KEY,
    sha TEXT UNIQUE NOT NULL,
    patch_id TEXT NOT NULL,
    author TEXT,
    committed_at TIMESTAMPTZ,
    subject TEXT,
    repo_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_commits_patch_id ON commits(patch_id);

CREATE TABLE IF NOT EXISTS scans (
    id BIGSERIAL PRIMARY KEY,
    commit_id BIGINT REFERENCES commits(id) ON DELETE CASCADE,
    status TEXT CHECK (status IN ('pending', 'running', 'done', 'failed')),
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
