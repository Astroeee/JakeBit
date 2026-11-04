-- Habits can have their own emoji logo (PostgreSQL version of migrations/007_habit_icon.sql)
ALTER TABLE habits ADD COLUMN IF NOT EXISTS icon TEXT;