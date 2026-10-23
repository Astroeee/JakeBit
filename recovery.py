import secrets
from flask import (Blueprint, flash, g, make_response, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
import ratelimit
from auth import login_required
from db import get_db

bp = Blueprint("recovery", __name__)

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"            # no 0/O or 1/I, so codes are easy to read
DUMMY_HASH = generate_password_hash("not-a-real-code")   # so unknown accounts take as long to check as real ones
RESET_FAILURES_PER_ACCOUNT = (5, 15 * 60)
RESET_FAILURES_PER_IP = (20, 15 * 60)


def new_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(16))   # 16 characters = 80 bits
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def normalize(code):
    """Ignore case, dashes and spaces when someone types their code."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def hash_code(code):
    return generate_password_hash(normalize(code))   # stored like a password, never in plain text


def show_once(code):
    """Keep the code in the session just long enough to display it on the next page."""
    session["show_recovery_code"] = code
    return redirect(url_for("recovery.show"))


@bp.route("/recovery-code")
def show():
    code = session.pop("show_recovery_code", None)   # pop = it can only be shown one time
    if code is None:
        return redirect(url_for("tracking.dashboard") if g.user else url_for("auth.login"))
    response = make_response(render_template("recovery_code.html", code=code))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/settings/recovery", methods=("POST",))
@login_required
def regenerate():
    db = get_db()
    scope = f"login:account:{g.user['username'].lower()}"   # same counter as login, so this form can't be used to guess passwords
    if ratelimit.too_many(db, scope, *RESET_FAILURES_PER_ACCOUNT):
        flash("Too many failed attempts. Please wait 15 minutes and try again.")
        return redirect(url_for("settings.settings"))

    row = db.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], request.form.get("password", "")):
        ratelimit.record(db, scope)
        flash("That password isn't right.")
        return redirect(url_for("settings.settings"))

    code = new_code()
    db.execute("UPDATE users SET recovery_hash = ? WHERE id = ?", (hash_code(code), g.user["id"]))
    db.commit()
    return show_once(code)


@bp.route("/reset-password", methods=("GET", "POST"))
def reset():
    if g.user:
        return redirect(url_for("tracking.dashboard"))

    if request.method == "POST":
        db = get_db()
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        key = identifier.lower()[:100]
        account_scope = f"reset:account:{key}"
        ip_scope = f"reset:ip:{ratelimit.client_ip()}"

        if (ratelimit.too_many(db, account_scope, *RESET_FAILURES_PER_ACCOUNT)
                or ratelimit.too_many(db, ip_scope, *RESET_FAILURES_PER_IP)):
            flash("Too many attempts. Please wait 15 minutes and try again.")
            return render_template("reset_password.html"), 429

        if len(password) < 8 or len(password) > 128 or password != confirm:
            flash("The new password must be 8 to 128 characters and match the confirmation.")
            return render_template("reset_password.html")

        user = db.execute(
            "SELECT id, recovery_hash FROM users WHERE username = ? OR email = ?",
            (identifier, identifier.lower()),
        ).fetchone()
        stored = user["recovery_hash"] if user and user["recovery_hash"] else None

        # Always run one hash check, and give one vague message for every kind of failure
        matches = check_password_hash(stored or DUMMY_HASH, normalize(request.form.get("code", "")))
        if stored is None or not matches:
            ratelimit.record(db, account_scope)
            ratelimit.record(db, ip_scope)
            flash("That username (or email) and recovery code don't match.")
            return render_template("reset_password.html")

        # Success: set the new password AND replace the code (each code works only once)
        code = new_code()
        db.execute(
            "UPDATE users SET password_hash = ?, recovery_hash = ? WHERE id = ?",
            (generate_password_hash(password), hash_code(code), user["id"]),
        )
        db.commit()
        ratelimit.clear(db, account_scope)
        ratelimit.clear(db, f"login:account:{key}")   # also lift any login lockout on that account
        flash("Password changed. Save your NEW recovery code below: the old one no longer works.")
        return show_once(code)

    return render_template("reset_password.html")