ALTER TABLE commits ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    commit_id BIGINT NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('doc_summary', 'doc_detail', 'finding', 'diff', 'file')),
    source_ref TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_commit_id ON chunks(commit_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
