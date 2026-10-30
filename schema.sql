DROP TABLE IF EXISTS rate_events;
DROP TABLE IF EXISTS avatar_images;
DROP TABLE IF EXISTS shared_members;
DROP TABLE IF EXISTS friendships;
DROP TABLE IF EXISTS habit_completions;
DROP TABLE IF EXISTS habits;
DROP TABLE IF EXISTS shared_habits;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- "Andre" and "andre" count as the same
    email            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash    TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Look and feel, saved per account
    theme            TEXT NOT NULL DEFAULT 'purple',
    bg               TEXT NOT NULL DEFAULT 'plain',
    card             TEXT NOT NULL DEFAULT 'soft',
    fur              TEXT NOT NULL DEFAULT 'red',
    mascot_name      TEXT NOT NULL DEFAULT 'Mochi',
    -- Privacy: what accepted friends are allowed to see (1 = yes, 0 = no)
    show_scores      INTEGER NOT NULL DEFAULT 1,
    show_habit_names INTEGER NOT NULL DEFAULT 0,
    avatar           TEXT,  -- random tag that changes with each new picture (NULL = no picture)
    recovery_hash    TEXT   -- hash of the one-time recovery code (NULL = none yet)
);

-- The profile picture itself (a 256x256 JPEG), kept in the database so it works on any host
CREATE TABLE avatar_images (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data    BLOB NOT NULL
);

-- A habit done together by a pair or group. Each member also gets their own row in `habits`.
CREATE TABLE shared_habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    category   TEXT,
    frequency  TEXT NOT NULL DEFAULT 'daily',
    creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    category   TEXT,
    frequency  TEXT NOT NULL DEFAULT 'daily',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active     INTEGER NOT NULL DEFAULT 1,
    weekly_target INTEGER NOT NULL DEFAULT 1,
    days_mask     INTEGER NOT NULL DEFAULT 127,   -- which weekdays (Mon = bit 0) when frequency = 'custom'
    -- Set when this habit is someone's copy of a shared habit. If the group is deleted,
    -- the habit simply becomes a normal personal habit and keeps its history.
    shared_id  INTEGER REFERENCES shared_habits(id) ON DELETE SET NULL
);

-- A person can only have one copy of each shared habit
CREATE UNIQUE INDEX idx_one_habit_per_shared ON habits (user_id, shared_id) WHERE shared_id IS NOT NULL;

CREATE TABLE habit_completions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id        INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    completion_date TEXT NOT NULL,          -- stored as YYYY-MM-DD
    completed       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (habit_id, completion_date)      -- prevents duplicate records per day
);

-- One row per friendship. "pending" = request sent, "accepted" = you're friends.
CREATE TABLE friendships (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted')),
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (requester_id != addressee_id)
);

CREATE UNIQUE INDEX idx_friendship_pair
    ON friendships (MIN(requester_id, addressee_id), MAX(requester_id, addressee_id));

-- Who is in which shared habit. "invited" until they accept, then "joined".
CREATE TABLE shared_members (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shared_id  INTEGER NOT NULL REFERENCES shared_habits(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'joined')),
    invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (shared_id, user_id)
);

-- Remembers recent events (failed logins, sign-ups, friend requests) for rate limiting
CREATE TABLE rate_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scope   TEXT NOT NULL,
    created REAL NOT NULL      -- unix time in seconds
);
CREATE INDEX idx_rate_events_scope ON rate_events (scope, created);