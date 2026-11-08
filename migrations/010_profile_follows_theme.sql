-- Profile pages follow the chosen theme's colour unless a fixed accent was picked
UPDATE users SET profile_accent = 'theme' WHERE profile_accent IN ('terracotta', 'purple');