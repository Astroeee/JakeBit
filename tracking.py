import calendar as cal
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, abort, g
from db import get_db
from auth import login_required

bp = Blueprint("tracking", __name__)

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def mask_to_days(mask):
    """A saved day mask -> {0, 2, 4} for Mon, Wed, Fri (bit 0 = Monday)."""
    return {i for i in range(7) if mask >> i & 1}


def days_to_mask(days):
    return sum(1 << i for i in set(days))


def is_required(frequency, day, days_mask=127):
    """Is a daily-style habit expected on this day? (Weekly habits are judged by week.)"""
    if frequency == "weekdays":
        return day.weekday() < 5
    if frequency == "custom":
        return bool(days_mask >> day.weekday() & 1)
    return True


def describe_schedule(frequency, weekly_target=1, days_mask=127):
    """Human-friendly schedule text, like 'Daily' or 'Mon, Wed, Fri'."""
    if frequency == "weekly":
        return f"{weekly_target}× per week"
    if frequency == "custom":
        return ", ".join(DAY_NAMES[i] for i in sorted(mask_to_days(days_mask))) or "No days"
    return frequency.capitalize()


def week_start(day):
    """The Monday of the week that contains `day`."""
    return day - timedelta(days=day.weekday())


def weekly_streaks(done_dates, today, target):
    """Streaks for a weekly goal. A week (Mon-Sun) is 'met' with at least `target` completions.
    Returns (current, longest) in WEEKS."""
    counts = {}
    for d in done_dates:
        ws = week_start(d)
        counts[ws] = counts.get(ws, 0) + 1
    met = {ws for ws, n in counts.items() if n >= target}
    if not met:
        return 0, 0

    week = week_start(today)
    if week not in met:               # this week is still in progress, so it doesn't break the streak
        week -= timedelta(days=7)
    current = 0
    while week in met:
        current += 1
        week -= timedelta(days=7)

    longest = run = 0
    previous = None
    for ws in sorted(met):
        run = run + 1 if previous is not None and ws - previous == timedelta(days=7) else 1
        longest = max(longest, run)
        previous = ws
    return current, longest


def compute_streaks(frequency, done_dates, today, weekly_target=1, days_mask=127):
    """Return (current_streak, longest_streak). Daily, weekday and custom-day habits count
    scheduled DAYS in a row (days off never break a streak); weekly habits count WEEKS."""
    if not done_dates:
        return 0, 0
    if frequency == "weekly":
        return weekly_streaks(done_dates, today, weekly_target)
    if frequency == "custom" and days_mask == 0:
        return 0, 0                    # nothing is scheduled, so there can be no streak

    # CURRENT: walk backwards from today. If today isn't done yet, start from yesterday.
    current = 0
    day = today if today in done_dates else today - timedelta(days=1)
    while True:
        if not is_required(frequency, day, days_mask):
            day -= timedelta(days=1)   # a day off: skip it
        elif day in done_dates:
            current += 1
            day -= timedelta(days=1)
        else:
            break                      # a missed scheduled day ends the streak

    # LONGEST: walk forward from the first completion to today, tracking runs.
    longest = run = 0
    day = min(done_dates)
    while day <= today:
        if is_required(frequency, day, days_mask):
            if day in done_dates:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        day += timedelta(days=1)
    return current, longest


def period_counts(frequency, target, done, start, end, days_mask=127):
    """Return (hits, required) between two dates (inclusive). Daily-style habits are counted day
    by day; weekly habits per complete week."""
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
            if is_required(frequency, day, days_mask):
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


def _parse_day(text, today):
    """A ?day=YYYY-MM-DD value -> a date that is never in the future (bad input means today)."""
    try:
        return min(date.fromisoformat(text or ""), today)
    except ValueError:
        return today


@bp.route("/")
@login_required
def dashboard():
    from insights import collect, day_items, today_summary, week_grid
    db = get_db()
    today = date.today()
    habits = collect(db, g.user["id"], today)

    day = _parse_day(request.args.get("day"), today)                    # the day shown in the side panel
    week = week_start(_parse_day(request.args.get("week"), today))      # the week shown in the grid
    grid, achieved = week_grid(habits, week, today)
    _, before = week_grid(habits, week - timedelta(days=7), today)

    done_count, percent = today_summary(habits, today)
    mood, message = mascot_status(percent, bool(habits))
    daily = [h for h in habits if not h["weekly"]]
    return render_template(
        "dashboard.html",
        today=today, day=day, week=week, grid=grid, achieved=achieved, change=achieved - before,
        items=day_items(habits, day),
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1) if day < today else None,
        prev_week=week - timedelta(days=7),
        next_week=week + timedelta(days=7) if week < week_start(today) else None,
        this_week=week_start(today),
        next_url=url_for("tracking.dashboard", day=day.isoformat(), week=week.isoformat()),
        total_habits=len(habits), done_today=done_count, percent=percent,
        best_streak=max((h["current"] for h in daily), default=0),
        best_longest=max((h["longest"] for h in daily), default=0),
        total_completions=sum(h["total"] for h in habits),
        mood=mood, message=message,
    )


@bp.route("/toggle/<int:habit_id>", methods=("POST",))
@login_required
def toggle(habit_id):
    """Mark a habit done for a date, or undo it if it's already done."""
    db = get_db()
    habit = db.execute(
        "SELECT id FROM habits WHERE id = ? AND user_id = ?", (habit_id, g.user["id"])
    ).fetchone()
    if habit is None:
        abort(404)

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

    nxt = request.form.get("next", "")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = url_for("tracking.dashboard")
    return redirect(nxt)


@bp.route("/calendar")
@login_required
def calendar_view():
    """The month tracker: one row per habit, one column per day. Click a cell to log or undo."""
    from insights import collect, daily_rates, scheduled
    db = get_db()
    today = date.today()
    habits = collect(db, g.user["id"], today)

    try:
        year, month = map(int, request.args.get("month", "").split("-"))
        first = date(year, month, 1)
    except ValueError:
        first = today.replace(day=1)
    if first > today.replace(day=1):
        first = today.replace(day=1)
    days = [first + timedelta(days=i) for i in range(cal.monthrange(first.year, first.month)[1])]

    rows, got_all, need_all = [], 0, 0
    for h in habits:
        cells, total, got, need = [], 0, 0, 0
        for d in days:
            sched = scheduled(h, d)
            if d in h["done"]:
                state = "done"
                total += 1
            elif d > today:
                state = "future"
            elif h["weekly"]:
                state = "open"
            elif sched:
                state = "miss"
            else:
                state = "off"                    # a day off, or before the habit existed
            if d <= today and sched and not h["weekly"]:
                need += 1
                got += 1 if d in h["done"] else 0
            cells.append({"day": d, "state": state})
        rows.append({"h": h, "cells": cells, "total": total, "rate": round(100 * got / need) if need else 0})
        got_all += got
        need_all += need

    last30 = daily_rates(habits, today - timedelta(days=29), today)
    due30 = sum(d["required"] for d in last30)
    daily = [h for h in habits if not h["weekly"]]
    first_year = min([h["created"].year for h in habits] + [today.year])

    def month_key(y, m):
        target = date(y, m, 1)
        return (target if target <= today else today.replace(day=1)).strftime("%Y-%m")

    return render_template(
        "calendar.html",
        habits=habits, rows=rows, days=days, first=first, today=today,
        months=[{"label": date(first.year, m, 1).strftime("%b").upper(), "key": month_key(first.year, m),
                 "active": m == first.month, "disabled": date(first.year, m, 1) > today} for m in range(1, 13)],
        years=[{"year": y, "key": month_key(y, first.month)} for y in range(first_year, today.year + 1)],
        next_url=url_for("tracking.calendar_view", month=first.strftime("%Y-%m")),
        best_current=max((h["current"] for h in daily), default=0),
        best_longest=max((h["longest"] for h in daily), default=0),
        consistency=round(100 * sum(d["done"] for d in last30) / due30) if due30 else 0,
        month_got=got_all, month_need=need_all,
        month_rate=round(100 * got_all / need_all) if need_all else 0,
    )
