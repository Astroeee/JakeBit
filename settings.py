from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from auth import login_required
from db import get_db

bp = Blueprint("settings", __name__)

# Allowed choices: (value, label, preview color). Anything not listed here is rejected.
OPTIONS = {
    "theme": [
        # Light themes
        ("purple", "Purple", "#7c3aed"),
        ("ocean", "Ocean", "#0284c7"),
        ("sunset", "Sunset", "#ea580c"),
        ("forest", "Forest", "#15803d"),
        ("rose", "Rose", "#e11d48"),
        ("mint", "Mint", "#0f766e"),
        ("sand", "Sand", "#b45309"),
        # Dark themes
        ("midnight", "Midnight", "#8b5cf6"),
        ("oceannight", "Ocean Night", "#38bdf8"),
        ("forestnight", "Forest Night", "#4ade80"),
        ("ember", "Ember", "#fb7185"),
        ("graphite", "Graphite", "#60a5fa"),
        ("amoled", "Amoled Black", "#c4b5fd"),
    ],
    "bg": [("plain", "Plain", None), ("dots", "Dots", None), ("gradient", "Gradient", None)],
    "card": [("soft", "Soft shadow", None), ("outline", "Outlined", None), ("flat", "Flat", None)],
    "fur": [
        ("red", "Golden", "#fdd699"),
        ("cream", "Cream", "#f3e7cf"),
        ("rust", "Red", "#c8602a"),
        ("brown", "Brown", "#8a5a3b"),
        ("black", "Black", "#3f3f4a"),
        ("blue", "Blue", "#8493aa"),
    ],
}
DARK_THEMES = {"midnight", "oceannight", "forestnight", "ember", "graphite", "amoled"}
DEFAULTS = {"theme": "purple", "bg": "plain", "card": "soft", "fur": "red", "mascot_name": "Mochi"}


def get_ui_settings():
    """The look for the current page: the logged-in user's saved choices,
    or the defaults for visitors who aren't logged in."""
    ui = dict(DEFAULTS)
    user = getattr(g, "user", None)
    if user is not None:
        for key, choices in OPTIONS.items():
            if user[key] in [c[0] for c in choices]:
                ui[key] = user[key]
        if user["mascot_name"]:
            ui["mascot_name"] = user["mascot_name"]
    # "dark" or "light": lets the CSS style every dark theme the same shared way
    ui["mode"] = "dark" if ui["theme"] in DARK_THEMES else "light"
    return ui


@bp.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    if request.method == "POST":
        error = None
        new = {}
        for key, choices in OPTIONS.items():
            value = request.form.get(key)
            if value not in [c[0] for c in choices]:
                error = "Please pick one of the available options."
            new[key] = value

        name = request.form.get("mascot_name", "").strip()
        if not name or len(name) > 16:
            error = "Mascot name must be 1 to 16 characters."

        if error:
            flash(error)
        else:
            # An unticked checkbox isn't sent by the browser at all, so "missing" means off
            show_scores = 1 if request.form.get("show_scores") else 0
            show_names = 1 if request.form.get("show_habit_names") else 0

            db = get_db()
            db.execute(
                "UPDATE users SET theme = ?, bg = ?, card = ?, fur = ?, mascot_name = ?, "
                "show_scores = ?, show_habit_names = ? WHERE id = ?",
                (new["theme"], new["bg"], new["card"], new["fur"], name,
                 show_scores, show_names, g.user["id"]),
            )
            db.commit()
            flash("Settings saved!")
            return redirect(url_for("settings.settings"))

    return render_template("settings.html", options=OPTIONS, dark_themes=DARK_THEMES)