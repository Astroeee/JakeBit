"""Numbers and chart shapes shared by the dashboard, the month tracker and the statistics page."""
import calendar as cal
from datetime import date, timedelta

from tracking import compute_streaks, describe_schedule, get_done_dates, is_required, period_counts, week_start

# Each habit gets its own colour, in the order the habits were created
COLORS = ["#7c5cff", "#ff4fc3", "#2f8cff", "#16c868", "#ff9f2e", "#12cfd0", "#f5576c", "#9aa514"]
CATEGORY_ICONS = {"Health": "💧", "Fitness": "💪", "Learning": "📚", "Mindfulness": "🧘",
                  "Productivity": "⚡", "Other": "⭐"}


def collect(db, user_id, today):
    """One dict per active habit with everything the pages need (colour, streaks, done dates...)."""
    rows = db.execute(
        "SELECT id, name, category, frequency, weekly_target, days_mask, shared_id, created_at FROM habits "
        "WHERE user_id = ? AND active = 1 ORDER BY id", (user_id,)).fetchall()
    habits = []
    for i, h in enumerate(rows):
        done = get_done_dates(db, h["id"])
        weekly = h["frequency"] == "weekly"
        current, longest = compute_streaks(h["frequency"], done, today, h["weekly_target"], h["days_mask"])
        per_week = (h["weekly_target"] if weekly else 5 if h["frequency"] == "weekdays"
                    else bin(h["days_mask"]).count("1") if h["frequency"] == "custom" else 7)
        habits.append({
            "id": h["id"], "name": h["name"], "category": h["category"], "shared_id": h["shared_id"],
            "icon": CATEGORY_ICONS.get(h["category"], "⭐"), "color": COLORS[i % len(COLORS)],
            "frequency": h["frequency"], "target": h["weekly_target"], "days_mask": h["days_mask"],
            "weekly": weekly, "unit": "w" if weekly else "", "per_week": per_week,
            "created": date.fromisoformat(h["created_at"][:10]), "done": done,
            "current": current, "longest": longest, "total": len(done),
            "schedule": describe_schedule(h["frequency"], h["weekly_target"], h["days_mask"]),
        })
    return habits


def scheduled(h, day):
    """Is this habit expected on `day`? (Weekly habits can be done on any day.)"""
    if h["weekly"]:
        return True
    return day >= h["created"] and is_required(h["frequency"], day, h["days_mask"])


def today_summary(habits, today):
    """Habits that need nothing more today: done, a rest day, or the weekly goal is already met."""
    this_week = week_start(today)
    satisfied = 0
    for h in habits:
        week_count = sum(1 for d in h["done"] if d >= this_week) if h["weekly"] else 0
        if (today in h["done"] or not is_required(h["frequency"], today, h["days_mask"])
                or (h["weekly"] and week_count >= h["target"])):
            satisfied += 1
    percent = round(100 * satisfied / len(habits)) if habits else 0
    return satisfied, percent


def week_grid(habits, start, today):
    """The week (Mon-Sun) starting at `start`: one row per habit plus the overall % achieved."""
    rows, got, need = [], 0, 0
    for h in habits:
        cells, n_done, n_need = [], 0, 0
        for i in range(7):
            d = start + timedelta(days=i)
            sched = scheduled(h, d)
            if d in h["done"]:
                state = "done"
            elif d > today:
                state = "future" if sched else "off"
            elif h["weekly"]:
                state = "open"
            elif sched:
                state = "today" if d == today else "miss"
            else:
                state = "off"
            cells.append({"day": d, "state": state})
            if d in h["done"] and (sched or h["weekly"]):
                n_done += 1
            if sched and not h["weekly"]:
                n_need += 1
        if h["weekly"]:
            n_need = h["target"]
        rows.append({"h": h, "cells": cells, "done": n_done, "need": n_need})
        got += min(n_done, n_need)
        need += n_need
    return rows, (round(100 * got / need) if need else 0)


def day_items(habits, day):
    """What the side panel shows for one day: done, still to do, or not scheduled (inactive)."""
    items = []
    for h in habits:
        week_count = 0
        if h["weekly"]:
            ws = week_start(day)
            week_count = sum(1 for d in h["done"] if ws <= d <= ws + timedelta(days=6))
        state = "done" if day in h["done"] else ("todo" if scheduled(h, day) else "off")
        items.append({"h": h, "state": state, "week_count": week_count})
    return items


def daily_rates(habits, start, end):
    """Day by day: how many of the daily-style habits scheduled that day were finished."""
    days = []
    daily = [h for h in habits if not h["weekly"]]
    d = start
    while d <= end:
        due = [h for h in daily if scheduled(h, d)]
        finished = sum(1 for h in due if d in h["done"])
        days.append({"day": d, "done": finished, "required": len(due),
                     "percent": round(100 * finished / len(due)) if due else 0})
        d += timedelta(days=1)
    return days


def rates(habits, today):
    """Completion rate over each habit's whole life (days for daily-style habits, weeks for weekly)."""
    out, total_hits, total_required = [], 0, 0
    for h in habits:
        start = min([h["created"]] + list(h["done"]))
        end = today if today in h["done"] else today - timedelta(days=1)   # today isn't a miss until it's over
        hits, required = period_counts(h["frequency"], h["target"], h["done"], start, end, h["days_mask"])
        out.append({**h, "rate": round(100 * hits / required) if required else 0})
        total_hits += hits
        total_required += required
    return out, (round(100 * total_hits / total_required) if total_required else 0)


def month_buckets(habits, today, count=12):
    """Completion % for each of the last `count` months (oldest first)."""
    buckets = []
    year, month = today.year, today.month
    for _ in range(count):
        buckets.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    buckets.reverse()
    points = []
    for year, month in buckets:
        first = date(year, month, 1)
        last = min(date(year, month, cal.monthrange(year, month)[1]), today)
        days = daily_rates(habits, first, last)
        done, required = sum(d["done"] for d in days), sum(d["required"] for d in days)
        points.append({"label": first.strftime("%b"), "percent": round(100 * done / required) if required else 0})
    return points


def line_chart(values, labels, width=620, height=250):
    """Turn percentages (0-100) into the SVG pieces of a smooth line chart."""
    left, right, top, bottom = 44, 14, 14, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(values)
    xs = [left + (plot_w * i / (n - 1) if n > 1 else plot_w / 2) for i in range(n)]
    ys = [top + plot_h * (1 - v / 100) for v in values]
    path = ""
    for i, (x, y) in enumerate(zip(xs, ys)):
        if i == 0:
            path = f"M{x:.1f},{y:.1f}"
        else:
            mid = (xs[i - 1] + x) / 2
            path += f" C{mid:.1f},{ys[i - 1]:.1f} {mid:.1f},{y:.1f} {x:.1f},{y:.1f}"
    baseline = top + plot_h
    area = f"{path} L{xs[-1]:.1f},{baseline:.1f} L{xs[0]:.1f},{baseline:.1f} Z" if n else ""
    step = max(1, n // 7)
    return {
        "width": width, "height": height, "path": path, "area": area, "left": left, "right": width - right,
        "grid": [{"y": top + plot_h * (1 - p / 100), "label": f"{p}%"} for p in (0, 25, 50, 75, 100)],
        "labels": [{"x": xs[i], "text": labels[i]} for i in range(0, n, step)],
        "last": {"x": xs[-1], "y": ys[-1]} if n else None,
    }
