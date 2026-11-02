"""Customisable profile pages: each person chooses what their page shows, and in what order."""
from datetime import date, timedelta
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from auth import login_required
from db import get_db
from scores import user_scores
from tracking import compute_streaks, get_done_dates, is_required

bp = Blueprint("profiles", __name__)

# The blocks a profile can show: key -> (title, short description)
WIDGETS = {
    "mascot": ("My chow chow", "Your mascot, in your fur colour"),
    "streak": ("Streak records", "Longest streak ever and best current streak"),
    "today": ("Today", "How many habits you have finished today"),
    "rate": ("Last 7 days", "Your completion rate this week"),
    "totals": ("All-time", "Total check-ins, active habits and days on Jakebit"),
    "badges": ("Achievements", "Badges you have earned"),
    "habits": ("Habits", "Your habit list with streaks"),
}
STAT_WIDGETS = {"streak", "today", "rate", "totals", "badges"}   # these need "show my scores" on
DEFAULT_WIDGETS = "mascot,streak,today,rate,badges,habits"
ACCENTS = {"purple": "#7c3aed", "blue": "#0284c7", "teal": "#0f766e", "green": "#15803d",
           "gold": "#b45309", "orange": "#ea580c", "pink": "#db2777", "slate": "#475569"}
BANNERS = {"mountain": "Mountains", "park": "Flower park", "forest": "Moonlit forest", "none": "Plain colour"}
# (key, name, how to earn it, stat used, amount needed)
BADGES = [
    ("first", "First check-in", "Finish a habit once", "total", 1),
    ("ten", "10 check-ins", "Finish habits 10 times", "total", 10),
    ("hundred", "100 check-ins", "Finish habits 100 times", "total", 100),
    ("week", "7-day streak", "Keep any habit going 7 days", "longest", 7),
    ("month", "30-day streak", "Keep any habit going 30 days", "longest", 30),
    ("century", "100-day streak", "Keep any habit going 100 days", "longest", 100),
    ("collector", "5 habits", "Have 5 active habits", "habit_count", 5),
]
PROFILE_COLUMNS = ("id, username, display_name, bio, profile_accent, profile_banner, profile_widgets, "
                   "searchable, show_scores, show_habit_names, fur, mascot_name, created_at")


def clean(text, limit):
    """One tidy line: no control characters, extra spaces collapsed, cut to `limit` characters."""
    text = "".join(ch if ch.isprintable() else " " for ch in text or "")
    return " ".join(text.split())[:limit]


def parse_widgets(text):
    """The saved comma-separated list -> valid widget keys, in order, without repeats."""
    return list(dict.fromkeys(k for k in (text or "").split(",") if k in WIDGETS))


def profile_stats(db, user_id, today):
    """Numbers shown in the stat widgets."""
    stats = user_scores(db, user_id, today)          # rate, hits, streak, habit_count
    habits = db.execute(
        "SELECT id, frequency, days_mask FROM habits WHERE user_id = ? AND active = 1", (user_id,)
    ).fetchall()
    longest = today_total = today_done = 0
    for h in habits:
        if h["frequency"] == "weekly":
            continue                                  # weekly habits count weeks, not days
        done = get_done_dates(db, h["id"])
        _, best = compute_streaks(h["frequency"], done, today, 1, h["days_mask"])
        longest = max(longest, best)
        if is_required(h["frequency"], today, h["days_mask"]):
            today_total += 1
            today_done += 1 if today in done else 0
    total = db.execute(
        "SELECT COUNT(*) FROM habit_completions c JOIN habits h ON h.id = c.habit_id WHERE h.user_id = ?",
        (user_id,),
    ).fetchone()[0]
    stats.update(longest=longest, today_total=today_total, today_done=today_done, total=total,
                 today_pct=round(100 * today_done / today_total) if today_total else 0)
    stats["badges"] = [{"name": n, "hint": hint, "earned": stats[field] >= need}
                       for _, n, hint, field, need in BADGES]
    return stats


def build_profile(db, user, viewer_id, today=None):
    """Everything the profile template needs, respecting the owner's privacy switches."""
    today = today or date.today()
    is_me = user["id"] == viewer_id
    can_stats = is_me or bool(user["show_scores"])
    can_habits = is_me or bool(user["show_habit_names"])
    stats = profile_stats(db, user["id"], today) if can_stats else None

    habits = None
    if can_habits:
        habits = []
        rows = db.execute(
            "SELECT id, name, category, frequency, weekly_target, days_mask FROM habits "
            "WHERE user_id = ? AND active = 1 ORDER BY created_at", (user["id"],)).fetchall()
        for h in rows:
            entry = {"name": h["name"], "category": h["category"],
                     "unit": "w" if h["frequency"] == "weekly" else ""}
            if can_stats:                              # streaks and dots count as "scores"
                done = get_done_dates(db, h["id"])
                entry["current"], entry["longest"] = compute_streaks(
                    h["frequency"], done, today, h["weekly_target"], h["days_mask"])
                entry["week"] = [{"day": today - timedelta(days=i), "done": (today - timedelta(days=i)) in done}
                                 for i in range(6, -1, -1)]
            habits.append(entry)

    widgets = parse_widgets(user["profile_widgets"])
    banner = user["profile_banner"] if user["profile_banner"] in BANNERS else "mountain"
    banner_value = 0
    if stats:
        banner_value = {"mountain": stats["longest"], "park": stats["today_pct"], "forest": stats["total"]}.get(banner, 0)
    hidden = [label for label, shown in (("stats", user["show_scores"]), ("habit names", user["show_habit_names"]))
              if not shown]
    return {
        "id": user["id"], "username": user["username"],
        "name": user["display_name"] or user["username"], "bio": user["bio"],
        "accent": ACCENTS.get(user["profile_accent"], ACCENTS["purple"]),
        "banner": banner, "banner_value": banner_value, "widgets": widgets,
        "since": user["created_at"][:10], "fur": user["fur"], "mascot_name": user["mascot_name"],
        "mood": "cheer" if stats and stats["today_total"] and stats["today_done"] >= stats["today_total"] else "happy",
        "stats": stats, "habits": habits, "widget_info": WIDGETS,
        "stats_note": (not can_stats) and any(w in STAT_WIDGETS for w in widgets),
        "friends_cant_see": " and ".join(hidden) if is_me and hidden else "",
    }


@bp.route("/profile")
@login_required
def my_profile():
    db = get_db()
    user = db.execute(f"SELECT {PROFILE_COLUMNS} FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    return render_template("profile.html", p=build_profile(db, user, g.user["id"]), is_me=True)


@bp.route("/profile/edit", methods=("GET", "POST"))
@login_required
def edit():
    db = get_db()
    user = db.execute(f"SELECT {PROFILE_COLUMNS} FROM users WHERE id = ?", (g.user["id"],)).fetchone()

    if request.method == "POST":
        accent = request.form.get("accent", "")
        banner = request.form.get("banner", "")
        chosen = list(dict.fromkeys(k for k in request.form.getlist("widget") if k in WIDGETS))  # keeps page order
        db.execute(
            "UPDATE users SET display_name = ?, bio = ?, profile_accent = ?, profile_banner = ?, "
            "profile_widgets = ?, searchable = ? WHERE id = ?",
            (clean(request.form.get("display_name"), 30) or None,
             clean(request.form.get("bio"), 160),
             accent if accent in ACCENTS else user["profile_accent"],
             banner if banner in BANNERS else user["profile_banner"],
             ",".join(chosen),
             1 if request.form.get("searchable") else 0,
             g.user["id"]),
        )
        db.commit()
        flash("Profile saved.")
        return redirect(url_for("profiles.my_profile"))

    on = parse_widgets(user["profile_widgets"])
    order = on + [k for k in WIDGETS if k not in on]       # shown ones first, in their order
    rows = [{"key": k, "title": WIDGETS[k][0], "hint": WIDGETS[k][1], "on": k in on} for k in order]
    return render_template("profile_edit.html", user=user, widgets=rows, accents=ACCENTS, banners=BANNERS)
