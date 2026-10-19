-- Remembers recent events (failed logins, sign-ups, friend requests) for rate limiting
CREATE TABLE IF NOT EXISTS rate_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scope   TEXT NOT NULL,
    created REAL NOT NULL      -- unix time in seconds
);
CREATE INDEX IF NOT EXISTS idx_rate_events_scope ON rate_events (scope, created);