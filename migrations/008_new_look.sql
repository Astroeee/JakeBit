-- New default look: terracotta theme and profile accent; retired themes map to their closest replacement
UPDATE users SET theme = 'terracotta' WHERE theme IN ('purple', 'sunset', 'rose');
UPDATE users SET theme = 'sage' WHERE theme IN ('forest', 'mint');
UPDATE users SET theme = 'midnight' WHERE theme = 'oceannight';
UPDATE users SET theme = 'graphite' WHERE theme IN ('forestnight', 'ember');
UPDATE users SET profile_accent = 'terracotta' WHERE profile_accent NOT IN ('blue', 'green', 'gold', 'pink', 'slate', 'black');