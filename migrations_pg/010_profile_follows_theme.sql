-- Profile pages follow the theme colour (PostgreSQL version of migrations/010_profile_follows_theme.sql)
ALTER TABLE users ALTER COLUMN profile_accent SET DEFAULT 'theme';
UPDATE users SET profile_accent = 'theme' WHERE profile_accent IN ('terracotta', 'purple');