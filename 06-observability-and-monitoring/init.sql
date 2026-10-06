CREATE TABLE IF NOT EXISTS interactions (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    policy_text TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    duration_seconds DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
    error TEXT,
    trace_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS interactions_created_at_idx
    ON interactions (created_at);

CREATE TABLE IF NOT EXISTS evaluations (
    interaction_id BIGINT PRIMARY KEY REFERENCES interactions(id) ON DELETE CASCADE,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_length INTEGER NOT NULL,
    is_rejection BOOLEAN NOT NULL,
    helpfulness TEXT NOT NULL CHECK (
        helpfulness IN ('helpful', 'not-helpful', 'NA')
    )
);

CREATE INDEX IF NOT EXISTS evaluations_evaluated_at_idx
    ON evaluations (evaluated_at);

GRANT SELECT ON interactions, evaluations TO tutorial;
