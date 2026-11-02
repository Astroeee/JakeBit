from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from auth import login_required, USERNAME_RE
from db import get_db, IntegrityError
import ratelimit
from profiles import PROFILE_COLUMNS, build_profile
from scores import user_scores

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
        "SELECT f.id, u.id AS user_id, u.username, u.display_name, u.bio FROM friendships f JOIN users u ON u.id = f.requester_id "
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
        "SELECT u.id, u.username, u.display_name, u.show_scores, f.id AS friendship_id "
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
            except IntegrityError:
                db.rollback()
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


@bp.route("/friends/search")
@login_required
def search():
    """Find people by username or display name. Each result shows picture, name and bio,
    so people with similar usernames are easy to tell apart."""
    db = get_db()
    me = g.user["id"]
    q = request.args.get("q", "").strip()[:30]
    results, note, relations = [], "", {}
    if len(q) == 1:
        note = "Type at least 2 characters."
    elif q:
        scope = f"friend-search:{me}"
        if ratelimit.too_many(db, scope, 30, 60 * 60):
            note = "You're searching too quickly. Please try again later."
        else:
            ratelimit.record(db, scope)
            # Escape % and _ so they are searched for literally instead of acting as wildcards
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            results = db.execute(
                "SELECT id, username, display_name, bio, created_at FROM users "
                "WHERE searchable = 1 AND id <> ? AND (username LIKE ? ESCAPE '\\' OR LOWER(display_name) LIKE LOWER(?) ESCAPE '\\') "
                "ORDER BY username LIMIT 12",
                (me, like, like),
            ).fetchall()
            for r in db.execute(
                    "SELECT id, requester_id, addressee_id, status FROM friendships "
                    "WHERE requester_id = ? OR addressee_id = ?", (me, me)):
                other = r["addressee_id"] if r["requester_id"] == me else r["requester_id"]
                relations[other] = r
            if not results:
                note = "No one found. People can switch off friend search in their profile settings."
    return render_template("friend_search.html", q=q, results=results, note=note, relations=relations, me=me)


@bp.route("/friends/<username>")
@login_required
def profile(username):
    db = get_db()
    friend = db.execute(f"SELECT {PROFILE_COLUMNS} FROM users WHERE username = ?", (username,)).fetchone()

    # Same 404 whether the user doesn't exist or just isn't your friend,
    # so this page can't be used to probe for accounts
    if friend is None or not are_friends(db, g.user["id"], friend["id"]):
        abort(404)
    return render_template("profile.html", p=build_profile(db, friend, g.user["id"]), is_me=False)
