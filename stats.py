from datetime import date, timedelta
from flask import Blueprint, render_template, g
from auth import login_required
from db import get_db
from tracking import compute_streaks, get_done_dates, is_required

bp = Blueprint("stats", __name__)


def completion_counts(frequency, done, created, today):
    """Return (days completed, days required) for one habit.
    Today only counts once it's done, so an unfinished day doesn't hurt your rate yet."""
    start = min([created] + list(done))
    end = today if today in done else today - timedelta(days=1)
    required = hits = 0
    day = start
    while day <= end:
        if is_required(frequency, day):
            required += 1
            if day in done:
                hits += 1
        day += timedelta(days=1)
    return hits, required


@bp.route("/statistics")
@login_required
def statistics():
    db = get_db()
    today = date.today()
    habits = db.execute(
        "SELECT id, name, frequency, created_at FROM habits WHERE user_id = ? AND active = 1",
        (g.user["id"],),
    ).fetchall()

    rows = []
    total_hits = total_required = 0
    for h in habits:
        done = get_done_dates(db, h["id"])
        created = date.fromisoformat(h["created_at"][:10])
        hits, required = completion_counts(h["frequency"], done, created, today)
        current, longest = compute_streaks(h["frequency"], done, today)
        rows.append({
            "name": h["name"], "frequency": h["frequency"], "created": created, "done": done,
            "rate": round(100 * hits / required) if required else 0,
            "current": current, "longest": longest, "total": len(done),
        })
        total_hits += hits
        total_required += required

    # Last 30 days: what share of the habits that were due each day did you finish?
    chart = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        due = [r for r in rows if r["created"] <= d and is_required(r["frequency"], d)]
        finished = sum(1 for r in due if d in r["done"])
        chart.append({
            "day": d, "done": finished, "required": len(due),
            "percent": round(100 * finished / len(due)) if due else 0,
        })

    ranked = sorted(rows, key=lambda r: (-r["rate"], r["name"]))
    return render_template(
        "statistics.html",
        rows=rows, chart=chart,
        overall_rate=round(100 * total_hits / total_required) if total_required else 0,
        best_current=max((r["current"] for r in rows), default=0),
        best_longest=max((r["longest"] for r in rows), default=0),
        total_done=sum(r["total"] for r in rows),
        most=ranked[:3],
        least=ranked[::-1][:3] if len(ranked) > 1 else [],
    )