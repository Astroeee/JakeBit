-- Customisable profile pages: display name, bio, accent colour, banner, widget list, friend-search switch
ALTER TABLE users ADD COLUMN display_name TEXT;
ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN profile_accent TEXT NOT NULL DEFAULT 'purple';
ALTER TABLE users ADD COLUMN profile_banner TEXT NOT NULL DEFAULT 'mountain';
ALTER TABLE users ADD COLUMN profile_widgets TEXT NOT NULL DEFAULT 'mascot,streak,today,rate,badges,habits';
ALTER TABLE users ADD COLUMN searchable INTEGER NOT NULL DEFAULT 1;