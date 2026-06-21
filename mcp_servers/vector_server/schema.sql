-- Vector MCP server schema. Run once on the cropcompass Postgres DB.
-- Requires pgvector (already enabled by scrapper/db/schema.sql).

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id    VARCHAR(200)    PRIMARY KEY,
    collection  VARCHAR(50)     NOT NULL DEFAULT 'icar',
    content     TEXT            NOT NULL,
    source      VARCHAR(500),
    metadata    JSONB           NOT NULL DEFAULT '{}'::jsonb,
    embedding   VECTOR(384)     NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- HNSW index for cosine distance. Tune as the corpus grows.
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_knowledge_collection
    ON knowledge_chunks (collection);

CREATE INDEX IF NOT EXISTS idx_knowledge_metadata_gin
    ON knowledge_chunks USING gin (metadata);
