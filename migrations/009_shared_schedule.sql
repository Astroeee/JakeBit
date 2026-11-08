-- Group habits can be weekly (n times a week) or custom (chosen weekdays), like personal habits
ALTER TABLE shared_habits ADD COLUMN weekly_target INTEGER NOT NULL DEFAULT 1;
ALTER TABLE shared_habits ADD COLUMN days_mask INTEGER NOT NULL DEFAULT 127;