-- Group habit schedules (PostgreSQL version of migrations/009_shared_schedule.sql)
ALTER TABLE shared_habits ADD COLUMN IF NOT EXISTS weekly_target INTEGER NOT NULL DEFAULT 1;
ALTER TABLE shared_habits ADD COLUMN IF NOT EXISTS days_mask INTEGER NOT NULL DEFAULT 127;