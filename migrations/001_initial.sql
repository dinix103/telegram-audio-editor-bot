CREATE TABLE IF NOT EXISTS preferences (
    user_id BIGINT PRIMARY KEY,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS job_counts (
    day DATE NOT NULL DEFAULT CURRENT_DATE,
    outcome TEXT NOT NULL,
    total BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY(day, outcome)
);
