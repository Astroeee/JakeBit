-- How many times per week a "weekly" habit should be done (ignored for other frequencies).
-- Databases created from the newest schema.sql already have this column, and the migration
-- runner treats that as already done.
ALTER TABLE habits ADD COLUMN weekly_target INTEGER NOT NULL DEFAULT 1;