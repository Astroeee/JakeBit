from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from db import get_db
from auth import login_required
from tracking import days_to_mask, mask_to_days

bp = Blueprint("habits", __name__)

CATEGORIES = ["Health", "Fitness", "Learning", "Mindfulness", "Productivity", "Other"]
FREQUENCIES = ["daily", "weekdays", "weekly", "custom"]
# The logos people can pick for a habit. Only these are accepted, so nothing else can be stored.
EMOJIS = [
    "💧", "🥗", "🍎", "💊", "😴", "🏃", "🚴", "🏊", "🧘", "💪", "🏋️", "⚽",
    "🏀", "🎾", "🥊", "🚶", "📚", "📖", "✏️", "🧠", "🎓", "💻", "🌍", "🗣️",
    "🎨", "🎵", "🎸", "📝", "⚡", "✅", "📅", "⏰", "💼", "🧹", "💰", "📈",
    "🎯", "🛏️", "🌱", "🌞", "🌙", "🐶", "📵", "🚭", "☕", "🍳", "🛁", "❤️",
    "⭐", "🔥",
]


def parse_icon(form):
    """The chosen emoji logo, or None (= use the category's icon) for anything not on the list."""
    icon = form.get("icon", "")
    return icon if icon in EMOJIS else None


def validate_habit_form(form):
    """Returns (error, name, category, frequency); error is None when everything is valid."""
    name = form.get("name", "").strip()
    category = form.get("category")
    frequency = form.get("frequency")

    error = None
    if not name:
        error = "Habit name is required."
    elif len(name) > 100:
        error = "Habit name must be 100 characters or less."
    elif category not in CATEGORIES:
        error = "Please choose a valid category."
    elif frequency not in FREQUENCIES:
        error = "Please choose a valid frequency."
    return error, name, category, frequency


def parse_weekly_target(form, frequency):
    """Times per week (1 to 7) for WEEKLY habits; other habits store 1. Returns (error, target)."""
    if frequency != "weekly":
        return None, 1
    raw = form.get("weekly_target", "1")
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 7:
        return "Choose between 1 and 7 times per week.", 1
    return None, int(raw)


def parse_days(form, frequency):
    """Which weekdays a CUSTOM habit is done on, as a bit mask (Monday = bit 0).
    Other habits store 127 (every day). Returns (error, mask)."""
    if frequency != "custom":
        return None, 127
    picked = form.getlist("days")
    if not picked or any(not (d.isascii() and d.isdigit() and int(d) <= 6) for d in picked):
        return "Pick at least one day of the week.", 127
    return None, days_to_mask(int(d) for d in picked)


def get_habit_or_404(db, habit_id):
    """Fetch a habit only if it belongs to the logged-in user, otherwise show a 404."""
    habit = db.execute(
        "SELECT id, name, category, frequency, weekly_target, days_mask, active, shared_id, icon "
        "FROM habits WHERE id = ? AND user_id = ?",
        (habit_id, g.user["id"]),
    ).fetchone()
    if habit is None:
        abort(404)
    return habit


def shared_redirect(habit):
    """Shared habits belong to the whole group, so they're managed from the group page."""
    flash("That's a shared habit. Manage it from its group page.")
    return redirect(url_for("shared.detail", shared_id=habit["shared_id"]))


@bp.route("/habits", methods=("GET", "POST"))
@login_required
def habits():
    db = get_db()

    if request.method == "POST":
        error, name, category, frequency = validate_habit_form(request.form)
        target, mask = 1, 127
        if error is None:
            error, target = parse_weekly_target(request.form, frequency)
        if error is None:
            error, mask = parse_days(request.form, frequency)
        if error:
            flash(error)
        else:
            db.execute(
                "INSERT INTO habits (user_id, name, category, frequency, weekly_target, days_mask, icon) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], name, category, frequency, target, mask, parse_icon(request.form)),
            )
            db.commit()
            flash("Habit added!")
            return redirect(url_for("habits.habits"))

    rows = db.execute(
        "SELECT id, name, category, frequency, weekly_target, days_mask, active, shared_id, icon FROM habits "
        "WHERE user_id = ? ORDER BY active DESC, created_at DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template(
        "habits.html", habits=rows, categories=CATEGORIES, frequencies=FREQUENCIES, emojis=EMOJIS
    )


@bp.route("/habits/<int:habit_id>/edit", methods=("GET", "POST"))
@login_required
def edit(habit_id):
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    me = g.user["id"]

    # A group habit: its creator changes the name and schedule for everyone, and every member
    # (creator included) can pick their own logo.
    shared = None
    if habit["shared_id"]:
        shared = db.execute("SELECT id, creator_id FROM shared_habits WHERE id = ?", (habit["shared_id"],)).fetchone()
    can_edit_core = shared is None or shared["creator_id"] == me
    group_page = url_for("shared.detail", shared_id=habit["shared_id"]) if shared else None

    if request.method == "POST":
        if not can_edit_core:
            db.execute("UPDATE habits SET icon = ? WHERE id = ? AND user_id = ?",
                       (parse_icon(request.form), habit_id, me))
            db.commit()
            flash("Logo updated!")
            return redirect(group_page)

        error, name, category, frequency = validate_habit_form(request.form)
        target, mask = 1, 127
        if error is None:
            error, target = parse_weekly_target(request.form, frequency)
        if error is None:
            error, mask = parse_days(request.form, frequency)
        if error:
            flash(error)
        elif shared is not None:
            db.execute("UPDATE shared_habits SET name = ?, category = ?, frequency = ?, weekly_target = ?, days_mask = ? "
                       "WHERE id = ?", (name, category, frequency, target, mask, shared["id"]))
            db.execute("UPDATE habits SET name = ?, category = ?, frequency = ?, weekly_target = ?, days_mask = ? "
                       "WHERE shared_id = ?", (name, category, frequency, target, mask, shared["id"]))
            db.execute("UPDATE habits SET icon = ? WHERE id = ? AND user_id = ?",
                       (parse_icon(request.form), habit_id, me))
            db.commit()
            flash("Group habit updated for everyone!")
            return redirect(group_page)
        else:
            db.execute(
                "UPDATE habits SET name = ?, category = ?, frequency = ?, weekly_target = ?, days_mask = ?, icon = ? "
                "WHERE id = ? AND user_id = ?",
                (name, category, frequency, target, mask, parse_icon(request.form), habit_id, me),
            )
            db.commit()
            flash("Habit updated!")
            return redirect(url_for("habits.habits"))

    return render_template(
        "edit_habit.html", habit=habit, categories=CATEGORIES, emojis=EMOJIS, shared=shared,
        frequencies=FREQUENCIES, can_edit_core=can_edit_core,
        selected_days=mask_to_days(habit["days_mask"]),
    )


@bp.route("/habits/<int:habit_id>/toggle-active", methods=("POST",))
@login_required
def toggle_active(habit_id):
    """Pause or re-activate a habit. A paused habit keeps its history."""
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    if habit["shared_id"]:
        return shared_redirect(habit)

    new_value = 0 if habit["active"] else 1
    db.execute("UPDATE habits SET active = ? WHERE id = ? AND user_id = ?",
               (new_value, habit_id, g.user["id"]))
    db.commit()
    flash("Habit activated." if new_value else "Habit paused.")
    return redirect(url_for("habits.habits"))


@bp.route("/habits/<int:habit_id>/delete", methods=("POST",))
@login_required
def delete(habit_id):
    """Permanently delete a habit (ON DELETE CASCADE removes its completion records)."""
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    if habit["shared_id"]:
        return shared_redirect(habit)

    db.execute("DELETE FROM habits WHERE id = ? AND user_id = ?", (habit_id, g.user["id"]))
    db.commit()
    flash("Habit deleted.")
    return redirect(url_for("habits.habits"))