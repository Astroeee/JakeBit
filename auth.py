import functools
import re
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,20}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@bp.before_app_request
def load_logged_in_user():
    """Runs before EVERY request: work out who is logged in and store them in g.user.
    The session cookie holds only the user's id; everything else comes from the database."""
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            "SELECT id, username, email, theme, bg, card, fur, mascot_name, "
            "show_scores, show_habit_names, avatar FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()  # None if the account no longer exists


def login_required(view):
    """Put this under a route to make it logged-in only. Visitors are sent to the login page."""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            # Remember the page they wanted (GET only: a POST can't be replayed after login)
            target = request.path if request.method == "GET" else None
            return redirect(url_for("auth.login", next=target))
        return view(**kwargs)
    return wrapped_view


def safe_next(target):
    """Only redirect to pages on THIS site. Blocks 'open redirect' tricks like ?next=//evil.com"""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("tracking.dashboard")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("tracking.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        # Validate everything on the server. Never trust the form.
        error = None
        if not USERNAME_RE.fullmatch(username):
            error = "Username must be 3 to 20 characters: letters, numbers or underscores."
        elif len(email) > 254 or not EMAIL_RE.fullmatch(email):
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif len(password) > 128:
            error = "Password must be 128 characters or less."
        elif password != confirm:
            error = "Passwords don't match."

        if error is None:
            db = get_db()
            try:
                # We store a salted hash, NEVER the password itself
                db.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                # The UNIQUE constraints on username/email caught a duplicate
                error = "That username or email is already taken."
            else:
                flash("Account created! Please log in.")
                return redirect(url_for("auth.login"))

        flash(error)

    return render_template("register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("tracking.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE username = ? OR email = ?",
            (identifier, identifier.lower()),
        ).fetchone()

        # One vague message for both "no such user" and "wrong password",
        # so attackers can't use this form to discover which usernames exist
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username or password.")
        else:
            session.clear()  # start a fresh session (prevents session fixation)
            session["user_id"] = user["id"]
            session.permanent = bool(request.form.get("remember"))  # stay logged in 30 days if ticked
            return redirect(safe_next(request.args.get("next")))

    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You've been logged out.")
    return redirect(url_for("auth.login"))