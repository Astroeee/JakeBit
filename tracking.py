import calendar as cal
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, abort, g
from db import get_db
from auth import login_required

bp = Blueprint("tracking", __name__)


def is_required(frequency, day):
    """Is a DAILY-style habit expected on this day? (Weekly habits are judged by week, not by day.)"""
    if frequency == "weekdays":
        return day.weekday() < 5  # Mon=0 ... Fri=4
    return True


def week_start(day):
    """The Monday of the week that contains `day`."""
    return day - timedelta(days=day.weekday())


def weekly_streaks(done_dates, today, target):
    """Streaks for a habit with a weekly goal. A week (Monday to Sunday) is 'met' when it has
    at least `target` completions. Returns (current, longest), counted in WEEKS."""
    counts = {}
    for d in done_dates:
        ws = week_start(d)
        counts[ws] = counts.get(ws, 0) + 1
    met = {ws for ws, n in counts.items() if n >= target}
    if not met:
        return 0, 0

    # CURRENT: if this week's goal isn't met YET, the week is still in progress,
    # so it doesn't break the streak. We count back from last week instead.
    week = week_start(today)
    if week not in met:
        week -= timedelta(days=7)
    current = 0
    while week in met:
        current += 1
        week -= timedelta(days=7)

    # LONGEST: walk through the met weeks in order and count runs of consecutive weeks
    longest = run = 0
    previous = None
    for ws in sorted(met):
        run = run + 1 if previous is not None and ws - previous == timedelta(days=7) else 1
        longest = max(longest, run)
        previous = ws
    return current, longest


def compute_streaks(frequency, done_dates, today, weekly_target=1):
    """Return (current_streak, longest_streak) for one habit.
    Daily and weekday habits count DAYS in a row; weekly habits count WEEKS in a row.
    done_dates is a set of date objects the habit was completed."""
    if not done_dates:
        return 0, 0
    if frequency == "weekly":
        return weekly_streaks(done_dates, today, weekly_target)

    # CURRENT STREAK: walk backwards from today, counting consecutive required days.
    # If today isn't done yet, start from yesterday so the day isn't "lost" until it ends.
    current = 0
    day = today if today in done_dates else today - timedelta(days=1)
    while True:
        if not is_required(frequency, day):
            day -= timedelta(days=1)   # skip days the habit isn't required (e.g. weekends)
        elif day in done_dates:
            current += 1
            day -= timedelta(days=1)
        else:
            break                      # a missed required day ends the streak

    # LONGEST STREAK: walk forward from the first completion to today, tracking runs.
    longest = run = 0
    day = min(done_dates)
    while day <= today:
        if is_required(frequency, day):
            if day in done_dates:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        day += timedelta(days=1)

    return current, longest


def period_counts(frequency, target, done, start, end):
    """Return (hits, required) for one habit between two dates (inclusive).
    Daily/weekday habits are counted day by day. Weekly habits are counted per COMPLETE
    week inside the period: required = the weekly goal, hits = completions (capped at the goal)."""
    hits = required = 0
    if frequency == "weekly":
        ws = week_start(start)
        if ws < start:                       # skip a partial first week
            ws += timedelta(days=7)
        while ws + timedelta(days=6) <= end:
            n = sum(1 for d in done if ws <= d <= ws + timedelta(days=6))
            required += target
            hits += min(n, target)
            ws += timedelta(days=7)
    else:
        day = start
        while day <= end:
            if is_required(frequency, day):
                required += 1
                if day in done:
                    hits += 1
            day += timedelta(days=1)
    return hits, required


def get_done_dates(db, habit_id):
    """All dates this habit was completed, as a set of date objects."""
    rows = db.execute(
        "SELECT completion_date FROM habit_completions WHERE habit_id = ? AND completed = 1",
        (habit_id,),
    ).fetchall()
    return {date.fromisoformat(r["completion_date"]) for r in rows}


def mascot_status(percent, has_habits):
    """Pick the mascot's mood and what he says, based on today's progress."""
    if not has_habits:
        return "happy", "Add your first habit and let's get going!"
    if percent == 100:
        return "cheer", "All done today! Treat time!"
    if percent == 0:
        return "sleepy", "Ready when you are. Let's knock out the first one!"
    if percent >= 50:
        return "happy", "More than halfway there. Keep it up!"
    return "happy", "Nice start! Keep the momentum going."


@bp.route("/")
@login_required
def dashboard():
    db = get_db()
    today = date.today()
    this_week = week_start(today)

    # Which habits to show: all, only those still to do, or only those done.
    # Anything unexpected in the URL falls back to "all".
    view = request.args.get("view", "all")
    if view not in ("all", "todo", "done"):
        view = "all"

    habits = db.execute(
        "SELECT id, name, category, frequency, weekly_target, shared_id FROM habits "
        "WHERE user_id = ? AND active = 1 ORDER BY created_at",
        (g.user["id"],),
    ).fetchall()

    cards = []
    for h in habits:
        done = get_done_dates(db, h["id"])
        weekly = h["frequency"] == "weekly"
        current, longest = compute_streaks(h["frequency"], done, today, h["weekly_target"])
        # Last 7 days, oldest first, for the little dot strip on each card
        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            week.append({"day": d, "done": d in done})
        week_count = sum(1 for d in done if d >= this_week) if weekly else 0
        done_today = today in done
        cards.append({
            "id": h["id"], "name": h["name"], "category": h["category"], "shared_id": h["shared_id"],
            "frequency": h["frequency"], "target": h["weekly_target"], "unit": "w" if weekly else "",
            "current": current, "longest": longest, "total": len(done),
            "week": week, "week_count": week_count, "done_today": done_today,
            # "satisfied" = nothing more to do today: done today, or (weekly habit) the goal is already met
            "satisfied": done_today or (weekly and week_count >= h["weekly_target"]),
        })

    # Stats always use ALL habits, so the percentage doesn't change when you filter
    done_count = sum(1 for c in cards if c["satisfied"])
    percent = round(100 * done_count / len(cards)) if cards else 0
    mood, message = mascot_status(percent, bool(cards))

    # Only the list of cards shown is filtered
    if view == "todo":
        visible = [c for c in cards if not c["satisfied"]]
    elif view == "done":
        visible = [c for c in cards if c["satisfied"]]
    else:
        visible = cards

    return render_template(
        "dashboard.html",
        today=today, cards=visible, view=view, total_habits=len(cards),
        done_today=done_count, percent=percent,
        # "days in a row" only makes sense for daily-style habits, so weekly ones are left out
        best_streak=max((c["current"] for c in cards if not c["unit"]), default=0),
        total_completions=sum(c["total"] for c in cards),
        mood=mood, message=message,
    )


@bp.route("/toggle/<int:habit_id>", methods=("POST",))
@login_required
def toggle(habit_id):
    """Mark a habit done for a date, or undo it if it's already done."""
    db = get_db()

    # Only allow changes to habits that belong to this user
    habit = db.execute(
        "SELECT id FROM habits WHERE id = ? AND user_id = ?", (habit_id, g.user["id"])
    ).fetchone()
    if habit is None:
        abort(404)

    # Validate the date: must be a real date, and not in the future
    try:
        day = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        abort(400)
    if day > date.today():
        abort(400)

    existing = db.execute(
        "SELECT id FROM habit_completions WHERE habit_id = ? AND completion_date = ?",
        (habit_id, day.isoformat()),
    ).fetchone()
    if existing:
        db.execute("DELETE FROM habit_completions WHERE id = ?", (existing["id"],))  # undo
    else:
        db.execute(
            "INSERT INTO habit_completions (habit_id, completion_date, completed) VALUES (?, ?, 1)",
            (habit_id, day.isoformat()),
        )
    db.commit()

    # Go back to the page the user came from (only internal paths are allowed)
    nxt = request.form.get("next", "")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = url_for("tracking.dashboard")
    return redirect(nxt)


@bp.route("/calendar")
@login_required
def calendar_view():
    db = get_db()
    today = date.today()
    habits = db.execute(
        "SELECT id, name, created_at, frequency, weekly_target FROM habits "
        "WHERE user_id = ? AND active = 1 ORDER BY name",
        (g.user["id"],),
    ).fetchall()
    if not habits:
        return render_template("calendar.html", habits=[])

    # Which habit? Which month? Fall back to sensible defaults if the URL is bad.
    habit_id = request.args.get("habit", type=int)
    selected = next((h for h in habits if h["id"] == habit_id), habits[0])
    try:
        year, month = map(int, request.args.get("month", "").split("-"))
        first = date(year, month, 1)
    except ValueError:
        first = today.replace(day=1)

    done = get_done_dates(db, selected["id"])
    created = date.fromisoformat(selected["created_at"][:10])
    weekly = selected["frequency"] == "weekly"

    # Build the month grid (weeks start on Sunday). Each day gets a status.
    rows = []
    for week in cal.Calendar(firstweekday=6).monthdatescalendar(first.year, first.month):
        row = []
        for d in week:
            if d.month != first.month:
                status = "outside"
            elif d > today:
                status = "future"
            elif d in done:
                status = "done"
            elif d >= created and not weekly:
                status = "missed"
            else:
                status = "none"  # before the habit existed, or a weekly habit (no single "required" day)
            row.append({"date": d, "status": status})
        rows.append(row)

    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    current, longest = compute_streaks(selected["frequency"], done, today, selected["weekly_target"])

    return render_template(
        "calendar.html",
        habits=habits, selected=selected, rows=rows, first=first, today=today,
        prev_key=prev_month.strftime("%Y-%m"),
        next_key=next_month.strftime("%Y-%m"),
        show_next=next_month <= today.replace(day=1),
        month_key=first.strftime("%Y-%m"),
        next_url=url_for("tracking.calendar_view", habit=selected["id"], month=first.strftime("%Y-%m")),
        current=current, longest=longest, unit_label="weeks" if weekly else "days",
        month_done=sum(1 for r in rows for c in r if c["status"] == "done"),
    )