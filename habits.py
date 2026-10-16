from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from db import get_db
from auth import login_required

bp = Blueprint("habits", __name__)

CATEGORIES = ["Health", "Fitness", "Learning", "Mindfulness", "Productivity", "Other"]
FREQUENCIES = ["daily", "weekdays", "weekly"]


def validate_habit_form(form):
    """Check the habit form. Used by Add, Edit and shared habits so the rules stay identical.
    Returns (error, name, category, frequency); error is None when everything is valid."""
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


def get_habit_or_404(db, habit_id):
    """Fetch a habit only if it belongs to the logged-in user, otherwise show a 404.
    Every edit, pause and delete goes through here so nobody can touch someone else's habit."""
    habit = db.execute(
        "SELECT id, name, category, frequency, active, shared_id FROM habits WHERE id = ? AND user_id = ?",
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
        if error:
            flash(error)
        else:
            # The ? placeholders are a parameterized query, which prevents SQL injection
            db.execute(
                "INSERT INTO habits (user_id, name, category, frequency) VALUES (?, ?, ?, ?)",
                (g.user["id"], name, category, frequency),
            )
            db.commit()
            flash("Habit added!")
            return redirect(url_for("habits.habits"))  # redirect so refreshing doesn't resubmit

    # Active habits first, paused ones at the bottom
    rows = db.execute(
        "SELECT id, name, category, frequency, active, shared_id FROM habits "
        "WHERE user_id = ? ORDER BY active DESC, created_at DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template(
        "habits.html", habits=rows, categories=CATEGORIES, frequencies=FREQUENCIES
    )


@bp.route("/habits/<int:habit_id>/edit", methods=("GET", "POST"))
@login_required
def edit(habit_id):
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    if habit["shared_id"]:
        return shared_redirect(habit)

    if request.method == "POST":
        error, name, category, frequency = validate_habit_form(request.form)
        if error:
            flash(error)
        else:
            # user_id in the WHERE clause is a second safety check on top of get_habit_or_404
            db.execute(
                "UPDATE habits SET name = ?, category = ?, frequency = ? WHERE id = ? AND user_id = ?",
                (name, category, frequency, habit_id, g.user["id"]),
            )
            db.commit()
            flash("Habit updated!")
            return redirect(url_for("habits.habits"))

    return render_template(
        "edit_habit.html", habit=habit, categories=CATEGORIES, frequencies=FREQUENCIES
    )


@bp.route("/habits/<int:habit_id>/toggle-active", methods=("POST",))
@login_required
def toggle_active(habit_id):
    """Pause or re-activate a habit. A paused habit keeps its history but disappears
    from the dashboard, calendar and statistics."""
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    if habit["shared_id"]:
        return shared_redirect(habit)

    new_value = 0 if habit["active"] else 1
    db.execute(
        "UPDATE habits SET active = ? WHERE id = ? AND user_id = ?",
        (new_value, habit_id, g.user["id"]),
    )
    db.commit()
    flash("Habit activated." if new_value else "Habit paused.")
    return redirect(url_for("habits.habits"))


@bp.route("/habits/<int:habit_id>/delete", methods=("POST",))
@login_required
def delete(habit_id):
    """Permanently delete a habit. ON DELETE CASCADE in the schema removes its
    completion records automatically."""
    db = get_db()
    habit = get_habit_or_404(db, habit_id)
    if habit["shared_id"]:
        return shared_redirect(habit)

    db.execute("DELETE FROM habits WHERE id = ? AND user_id = ?", (habit_id, g.user["id"]))
    db.commit()
    flash("Habit deleted.")
    return redirect(url_for("habits.habits"))