import sqlite3
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from auth import login_required, USERNAME_RE
from db import get_db
import ratelimit
from scores import user_scores
from tracking import compute_streaks, get_done_dates

bp = Blueprint("friends", __name__)


def are_friends(db, a, b):
    """True only if an ACCEPTED friendship exists between users a and b (either direction)."""
    row = db.execute(
        "SELECT 1 FROM friendships WHERE status = 'accepted' AND "
        "((requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?))",
        (a, b, b, a),
    ).fetchone()
    return row is not None


@bp.route("/friends")
@login_required
def friends():
    db = get_db()
    me = g.user["id"]
    today = date.today()

    # Requests other people sent to me
    incoming = db.execute(
        "SELECT f.id, u.username FROM friendships f JOIN users u ON u.id = f.requester_id "
        "WHERE f.addressee_id = ? AND f.status = 'pending' ORDER BY f.created_at",
        (me,),
    ).fetchall()

    # Requests I sent that haven't been answered yet
    sent = db.execute(
        "SELECT f.id, u.username FROM friendships f JOIN users u ON u.id = f.addressee_id "
        "WHERE f.requester_id = ? AND f.status = 'pending' ORDER BY f.created_at",
        (me,),
    ).fetchall()

    # My accepted friends. The CASE picks "the other person" whichever side I was on.
    friend_rows = db.execute(
        "SELECT u.id, u.username, u.show_scores, f.id AS friendship_id "
        "FROM friendships f "
        "JOIN users u ON u.id = CASE WHEN f.requester_id = ? THEN f.addressee_id ELSE f.requester_id END "
        "WHERE f.status = 'accepted' AND (f.requester_id = ? OR f.addressee_id = ?) "
        "ORDER BY u.username",
        (me, me, me),
    ).fetchall()

    # Leaderboard: me + friends. A friend with scores switched off is listed but not ranked,
    # and we never even calculate their numbers.
    board = [{"user_id": me, "username": g.user["username"], "is_me": True, "visible": True,
              **user_scores(db, me, today)}]
    for fr in friend_rows:
        if fr["show_scores"]:
            board.append({"user_id": fr["id"], "username": fr["username"], "is_me": False, "visible": True,
                          **user_scores(db, fr["id"], today)})
        else:
            board.append({"user_id": fr["id"], "username": fr["username"], "is_me": False, "visible": False,
                          "rate": 0, "hits": 0, "streak": 0, "habit_count": 0})

    board.sort(key=lambda e: (not e["visible"], -e["rate"], -e["streak"], e["username"].lower()))
    rank = 0
    for e in board:
        if e["visible"]:
            rank += 1
            e["rank"] = rank
        else:
            e["rank"] = None

    return render_template("friends.html", incoming=incoming, sent=sent, friends=friend_rows, board=board)


@bp.route("/friends/add", methods=("POST",))
@login_required
def add_friend():
    db = get_db()
    me = g.user["id"]

    # No more than 20 friend requests per hour per person
    scope = f"friend-request:{me}"
    if ratelimit.too_many(db, scope, 20, 60 * 60):
        flash("You're sending requests too quickly. Please try again later.")
        return redirect(url_for("friends.friends"))
    ratelimit.record(db, scope)

    username = request.form.get("username", "").strip()

    target = None
    error = None
    if not USERNAME_RE.fullmatch(username):
        error = "Please enter a valid username."
    else:
        target = db.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
        if target is None:
            error = "No user with that username."
        elif target["id"] == me:
            error = "You can't add yourself."

    if error is None:
        existing = db.execute(
            "SELECT id, requester_id, status FROM friendships "
            "WHERE (requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?)",
            (me, target["id"], target["id"], me),
        ).fetchone()

        if existing is None:
            try:
                db.execute(
                    "INSERT INTO friendships (requester_id, addressee_id) VALUES (?, ?)",
                    (me, target["id"]),
                )
                db.commit()
                flash(f"Friend request sent to {target['username']}.")
            except sqlite3.IntegrityError:
                error = "A request between you two already exists."
        elif existing["status"] == "accepted":
            error = "You're already friends."
        elif existing["requester_id"] == me:
            error = "You already sent a request to that person."
        else:
            # They already asked us, so adding them back simply accepts their request
            db.execute("UPDATE friendships SET status = 'accepted' WHERE id = ?", (existing["id"],))
            db.commit()
            flash(f"You're now friends with {target['username']}!")

    if error:
        flash(error)
    return redirect(url_for("friends.friends"))


@bp.route("/friends/<int:friendship_id>/accept", methods=("POST",))
@login_required
def accept(friendship_id):
    """Only the person who RECEIVED the request can accept it."""
    db = get_db()
    cur = db.execute(
        "UPDATE friendships SET status = 'accepted' "
        "WHERE id = ? AND addressee_id = ? AND status = 'pending'",
        (friendship_id, g.user["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        abort(404)
    flash("Friend request accepted!")
    return redirect(url_for("friends.friends"))


@bp.route("/friends/<int:friendship_id>/remove", methods=("POST",))
@login_required
def remove(friendship_id):
    """Decline a request, cancel one you sent, or unfriend. Either person involved may do it."""
    db = get_db()
    me = g.user["id"]
    cur = db.execute(
        "DELETE FROM friendships WHERE id = ? AND (requester_id = ? OR addressee_id = ?)",
        (friendship_id, me, me),
    )
    db.commit()
    if cur.rowcount == 0:
        abort(404)
    flash("Removed.")
    return redirect(url_for("friends.friends"))


@bp.route("/friends/<username>")
@login_required
def profile(username):
    db = get_db()
    friend = db.execute(
        "SELECT id, username, show_scores, show_habit_names FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    # Same 404 whether the user doesn't exist or just isn't your friend,
    # so this page can't be used to probe for accounts
    if friend is None or not are_friends(db, g.user["id"], friend["id"]):
        abort(404)

    today = date.today()
    scores = user_scores(db, friend["id"], today) if friend["show_scores"] else None

    # Habit names are only loaded if the friend allows it
    habits = []
    if friend["show_habit_names"]:
        rows = db.execute(
            "SELECT id, name, category, frequency FROM habits "
            "WHERE user_id = ? AND active = 1 ORDER BY created_at",
            (friend["id"],),
        ).fetchall()
        for h in rows:
            entry = {"name": h["name"], "category": h["category"]}
            # Per-habit streaks and dots count as "scores", so they need that switch too
            if friend["show_scores"]:
                done = get_done_dates(db, h["id"])
                entry["current"], entry["longest"] = compute_streaks(h["frequency"], done, today)
                entry["week"] = [
                    {"day": today - timedelta(days=i), "done": (today - timedelta(days=i)) in done}
                    for i in range(6, -1, -1)
                ]
            habits.append(entry)

    return render_template("friend_profile.html", friend=friend, scores=scores, habits=habits)