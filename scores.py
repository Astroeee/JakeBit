from datetime import date, timedelta
from tracking import compute_streaks, get_done_dates, is_required


def user_scores(db, user_id, today=None):
    """Summary numbers for one user over their ACTIVE habits: rate (last 7 days), hits, best streak."""
    today = today or date.today()
    habits = db.execute(
        "SELECT id, frequency, weekly_target, days_mask, created_at FROM habits "
        "WHERE user_id = ? AND active = 1",
        (user_id,),
    ).fetchall()

    window_start = today - timedelta(days=6)
    hits = required = best_streak = 0

    for h in habits:
        done = get_done_dates(db, h["id"])
        created = date.fromisoformat(h["created_at"][:10])

        if h["frequency"] == "weekly":
            if created <= window_start:      # judged over the last 7 days, once the habit is a week old
                n = sum(1 for d in done if window_start <= d <= today)
                required += h["weekly_target"]
                hits += min(n, h["weekly_target"])
            continue

        start = max(window_start, created)
        end = today if today in done else today - timedelta(days=1)
        day = start
        while day <= end:
            if is_required(h["frequency"], day, h["days_mask"]):
                required += 1
                if day in done:
                    hits += 1
            day += timedelta(days=1)

        current, _ = compute_streaks(h["frequency"], done, today, 1, h["days_mask"])
        best_streak = max(best_streak, current)

    return {
        "rate": round(100 * hits / required) if required else 0,
        "hits": hits,
        "streak": best_streak,
        "habit_count": len(habits),
    }