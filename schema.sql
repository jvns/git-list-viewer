CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    subject TEXT,
    from_addr TEXT,
    from_name TEXT,
    date_sent INTEGER,
    commit_id TEXT,
    root_message_id TEXT
);

-- Create index on commit_id for faster lookups during incremental indexing
CREATE INDEX IF NOT EXISTS idx_commit_id ON messages (commit_id);