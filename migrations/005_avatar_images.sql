-- Profile pictures now live in the database (so the app also works on hosts with no persistent disk)
CREATE TABLE IF NOT EXISTS avatar_images (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data    BLOB NOT NULL
);