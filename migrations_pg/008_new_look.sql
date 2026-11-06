-- New default look (PostgreSQL version of migrations/008_new_look.sql)
ALTER TABLE users ALTER COLUMN theme SET DEFAULT 'terracotta';
ALTER TABLE users ALTER COLUMN profile_accent SET DEFAULT 'terracotta';
UPDATE users SET theme = 'terracotta' WHERE theme IN ('purple', 'sunset', 'rose');
UPDATE users SET theme = 'sage' WHERE theme IN ('forest', 'mint');
UPDATE users SET theme = 'midnight' WHERE theme = 'oceannight';
UPDATE users SET theme = 'graphite' WHERE theme IN ('forestnight', 'ember');
UPDATE users SET profile_accent = 'terracotta' WHERE profile_accent NOT IN ('blue', 'green', 'gold', 'pink', 'slate', 'black');