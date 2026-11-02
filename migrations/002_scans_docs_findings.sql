CREATE TABLE IF NOT EXISTS docs (
    id BIGSERIAL PRIMARY KEY,
    commit_id BIGINT REFERENCES commits(id) ON DELETE CASCADE,
    kind TEXT CHECK (kind IN ('summary', 'detail')),
    body_md TEXT NOT NULL,
    model TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (commit_id, kind)
);

CREATE TABLE IF NOT EXISTS findings (
    id BIGSERIAL PRIMARY KEY,
    commit_id BIGINT REFERENCES commits(id) ON DELETE CASCADE,
    source TEXT CHECK (source IN ('semgrep', 'gitleaks', 'llm')),
    rule_id TEXT,
    severity TEXT CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    file TEXT,
    line INT,
    cwe TEXT,
    title TEXT,
    explanation TEXT,
    fix TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'ignored', 'fixed')),
    ignore_reason TEXT,
    fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (commit_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_findings_commit_id ON findings(commit_id);
CREATE INDEX IF NOT EXISTS idx_findings_fingerprint ON findings(fingerprint);
