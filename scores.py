from datetime import date, timedelta
from tracking import compute_streaks, get_done_dates, is_required


def user_scores(db, user_id, today=None):
    """Summary numbers for one user, over their ACTIVE habits:
    rate   = % of required habit-days completed in the last 7 days
    hits   = how many check-ins that is
    streak = their best current streak across habits"""
    today = today or date.today()
    habits = db.execute(
        "SELECT id, frequency, created_at FROM habits WHERE user_id = ? AND active = 1",
        (user_id,),
    ).fetchall()

    week_start = today - timedelta(days=6)
    hits = required = best_streak = 0

    for h in habits:
        done = get_done_dates(db, h["id"])
        created = date.fromisoformat(h["created_at"][:10])

        # Don't count days before the habit existed, and don't count today
        # as a miss until it's done (the day isn't over yet)
        start = max(week_start, created)
        end = today if today in done else today - timedelta(days=1)
        day = start
        while day <= end:
            if is_required(h["frequency"], day):
                required += 1
                if day in done:
                    hits += 1
            day += timedelta(days=1)

        current, _ = compute_streaks(h["frequency"], done, today)
        best_streak = max(best_streak, current)

    return {
        "rate": round(100 * hits / required) if required else 0,
        "hits": hits,
        "streak": best_streak,
        "habit_count": len(habits),
    }