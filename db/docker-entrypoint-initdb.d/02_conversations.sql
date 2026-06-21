-- Conversation history for the agent service.
-- Auto-applied by docker-compose via /docker-entrypoint-initdb.d/

CREATE TABLE IF NOT EXISTS conversation_turns (
    id          BIGSERIAL       PRIMARY KEY,
    session_id  VARCHAR(64)     NOT NULL,
    farmer_id   VARCHAR(64),
    role        VARCHAR(10)     NOT NULL CHECK (role IN ('user','assistant')),
    content     TEXT            NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns (session_id, id);
