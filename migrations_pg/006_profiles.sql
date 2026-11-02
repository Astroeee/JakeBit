-- Customisable profile pages (PostgreSQL version of migrations/006_profiles.sql)
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_accent TEXT NOT NULL DEFAULT 'purple';
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_banner TEXT NOT NULL DEFAULT 'mountain';
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_widgets TEXT NOT NULL DEFAULT 'mascot,streak,today,rate,badges,habits';
ALTER TABLE users ADD COLUMN IF NOT EXISTS searchable INTEGER NOT NULL DEFAULT 1;