from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from auth import login_required
from db import get_db
from friends import are_friends
from habits import validate_habit_form, CATEGORIES, FREQUENCIES
from tracking import compute_streaks, get_done_dates

bp = Blueprint("shared", __name__)

MAX_MEMBERS = 10  # including the creator


def my_friends(db, me):
    """Accepted friends of user `me`, as (id, username) rows."""
    return db.execute(
        "SELECT u.id, u.username FROM friendships f "
        "JOIN users u ON u.id = CASE WHEN f.requester_id = ? THEN f.addressee_id ELSE f.requester_id END "
        "WHERE f.status = 'accepted' AND (f.requester_id = ? OR f.addressee_id = ?) "
        "ORDER BY u.username",
        (me, me, me),
    ).fetchall()


def get_shared_or_404(db, shared_id, user_id):
    """Load a shared habit, but ONLY if user_id has joined it.
    Everyone else gets the same 404, so outsiders can't tell whether a group exists."""
    shared = db.execute(
        "SELECT id, name, category, frequency, creator_id FROM shared_habits WHERE id = ?",
        (shared_id,),
    ).fetchone()
    member = db.execute(
        "SELECT 1 FROM shared_members WHERE shared_id = ? AND user_id = ? AND status = 'joined'",
        (shared_id, user_id),
    ).fetchone()
    if shared is None or member is None:
        abort(404)
    return shared


def join_habit(db, shared, user_id):
    """Give a user their own personal habit row linked to the shared habit.
    Their check-offs go in the normal habit_completions table, so the dashboard,
    calendar and statistics all work without any changes."""
    db.execute(
        "INSERT INTO habits (user_id, name, category, frequency, shared_id) VALUES (?, ?, ?, ?, ?)",
        (user_id, shared["name"], shared["category"], shared["frequency"], shared["id"]),
    )


def clean_invitees(db, me, raw_values, slots_left):
    """Turn the ticked friend checkboxes into a validated set of user ids.
    Returns (ids, error). Never trust the form: check every id on the server."""
    ids = set()
    for raw in raw_values:
        if not (raw.isascii() and raw.isdigit()):
            return set(), "Invalid friend selection."
        ids.add(int(raw))
    ids.discard(me)
    if len(ids) > slots_left:
        return set(), f"A group can have at most {MAX_MEMBERS} people."
    for uid in ids:
        if not are_friends(db, me, uid):
            return set(), "You can only invite your friends."
    return ids, None


@bp.route("/shared")
@login_required
def index():
    db = get_db()
    me = g.user["id"]

    invites = db.execute(
        "SELECT s.id, s.name, s.frequency, u.username AS invited_by_name "
        "FROM shared_members m "
        "JOIN shared_habits s ON s.id = m.shared_id "
        "JOIN users u ON u.id = m.invited_by "
        "WHERE m.user_id = ? AND m.status = 'invited' ORDER BY m.created_at",
        (me,),
    ).fetchall()

    mine = db.execute(
        "SELECT s.id, s.name, s.category, s.frequency, "
        "(SELECT COUNT(*) FROM shared_members x WHERE x.shared_id = s.id AND x.status = 'joined') AS member_count "
        "FROM shared_members m JOIN shared_habits s ON s.id = m.shared_id "
        "WHERE m.user_id = ? AND m.status = 'joined' ORDER BY s.created_at DESC",
        (me,),
    ).fetchall()

    return render_template(
        "shared.html", invites=invites, mine=mine, friends=my_friends(db, me),
        categories=CATEGORIES, frequencies=FREQUENCIES, max_invites=MAX_MEMBERS - 1,
    )


@bp.route("/shared/create", methods=("POST",))
@login_required
def create():
    db = get_db()
    me = g.user["id"]

    # Same validation rules as a normal habit
    error, name, category, frequency = validate_habit_form(request.form)
    invitees = set()
    if error is None:
        invitees, error = clean_invitees(db, me, request.form.getlist("invite"), MAX_MEMBERS - 1)
    if error:
        flash(error)
        return redirect(url_for("shared.index"))

    # Nothing is saved until db.commit(), so if anything fails the whole group is discarded
    cur = db.execute(
        "INSERT INTO shared_habits (name, category, frequency, creator_id) VALUES (?, ?, ?, ?)",
        (name, category, frequency, me),
    )
    shared_id = cur.lastrowid
    shared = {"id": shared_id, "name": name, "category": category, "frequency": frequency}

    # The creator joins immediately; everyone else is invited
    db.execute(
        "INSERT INTO shared_members (shared_id, user_id, status, invited_by) VALUES (?, ?, 'joined', ?)",
        (shared_id, me, me),
    )
    join_habit(db, shared, me)
    for uid in invitees:
        db.execute(
            "INSERT INTO shared_members (shared_id, user_id, status, invited_by) VALUES (?, ?, 'invited', ?)",
            (shared_id, uid, me),
        )
    db.commit()
    flash("Shared habit created!")
    return redirect(url_for("shared.detail", shared_id=shared_id))


@bp.route("/shared/<int:shared_id>/accept", methods=("POST",))
@login_required
def accept(shared_id):
    db = get_db()
    me = g.user["id"]
    shared = db.execute(
        "SELECT id, name, category, frequency FROM shared_habits WHERE id = ?", (shared_id,)
    ).fetchone()
    if shared is None:
        abort(404)

    # Only works if there's a pending invitation for THIS user
    cur = db.execute(
        "UPDATE shared_members SET status = 'joined' WHERE shared_id = ? AND user_id = ? AND status = 'invited'",
        (shared_id, me),
    )
    if cur.rowcount == 0:
        abort(404)

    join_habit(db, shared, me)
    db.commit()
    flash("You joined the shared habit!")
    return redirect(url_for("shared.detail", shared_id=shared_id))


@bp.route("/shared/<int:shared_id>/decline", methods=("POST",))
@login_required
def decline(shared_id):
    db = get_db()
    cur = db.execute(
        "DELETE FROM shared_members WHERE shared_id = ? AND user_id = ? AND status = 'invited'",
        (shared_id, g.user["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        abort(404)
    flash("Invitation declined.")
    return redirect(url_for("shared.index"))


@bp.route("/shared/<int:shared_id>")
@login_required
def detail(shared_id):
    db = get_db()
    me = g.user["id"]
    today = date.today()
    shared = get_shared_or_404(db, shared_id, me)

    rows = db.execute(
        "SELECT m.user_id, m.status, u.username FROM shared_members m "
        "JOIN users u ON u.id = m.user_id WHERE m.shared_id = ? ORDER BY u.username",
        (shared_id,),
    ).fetchall()

    members, pending, done_sets = [], [], []
    my_habit_id, my_done_today = None, False
    for r in rows:
        if r["status"] != "joined":
            pending.append({"user_id": r["user_id"], "username": r["username"]})
            continue

        # This member's personal copy of the habit
        habit = db.execute(
            "SELECT id FROM habits WHERE shared_id = ? AND user_id = ?", (shared_id, r["user_id"])
        ).fetchone()
        done = get_done_dates(db, habit["id"]) if habit else set()
        done_sets.append(done)

        current, longest = compute_streaks(shared["frequency"], done, today)
        if r["user_id"] == me and habit:
            my_habit_id, my_done_today = habit["id"], today in done
        members.append({
            "user_id": r["user_id"], "username": r["username"], "is_me": r["user_id"] == me,
            "done_today": today in done, "current": current, "longest": longest,
            "week": [
                {"day": today - timedelta(days=i), "done": (today - timedelta(days=i)) in done}
                for i in range(6, -1, -1)
            ],
        })

    # GROUP STREAK: a day only counts if EVERY member completed it, so we intersect
    # everyone's completion dates and run the normal streak logic on the result.
    group_done = set.intersection(*done_sets) if done_sets else set()
    group_current, group_longest = compute_streaks(shared["frequency"], group_done, today)

    # Only the creator can invite more people, and only from their own friends
    is_creator = shared["creator_id"] == me
    invitable = []
    if is_creator:
        member_ids = {r["user_id"] for r in rows}
        invitable = [f for f in my_friends(db, me) if f["id"] not in member_ids]

    return render_template(
        "shared_detail.html", shared=shared, members=members, pending=pending,
        done_count=sum(1 for m in members if m["done_today"]),
        group_current=group_current, group_longest=group_longest,
        my_habit_id=my_habit_id, my_done_today=my_done_today, today=today,
        is_creator=is_creator, invitable=invitable,
    )


@bp.route("/shared/<int:shared_id>/invite", methods=("POST",))
@login_required
def invite(shared_id):
    db = get_db()
    me = g.user["id"]
    shared = get_shared_or_404(db, shared_id, me)
    if shared["creator_id"] != me:
        abort(403)  # only the creator can invite

    existing = {r["user_id"] for r in db.execute(
        "SELECT user_id FROM shared_members WHERE shared_id = ?", (shared_id,)
    ).fetchall()}
    ids, error = clean_invitees(db, me, request.form.getlist("invite"), MAX_MEMBERS - len(existing))
    ids -= existing  # skip anyone already in or invited

    if error:
        flash(error)
    elif not ids:
        flash("Pick at least one friend to invite.")
    else:
        for uid in ids:
            db.execute(
                "INSERT INTO shared_members (shared_id, user_id, status, invited_by) VALUES (?, ?, 'invited', ?)",
                (shared_id, uid, me),
            )
        db.commit()
        flash("Invitations sent!")
    return redirect(url_for("shared.detail", shared_id=shared_id))


@bp.route("/shared/<int:shared_id>/leave", methods=("POST",))
@login_required
def leave(shared_id):
    db = get_db()
    me = g.user["id"]
    shared = get_shared_or_404(db, shared_id, me)
    if shared["creator_id"] == me:
        flash("The creator can't leave. Delete the shared habit instead.")
        return redirect(url_for("shared.detail", shared_id=shared_id))

    # Keep the member's history: their copy just becomes a normal personal habit
    db.execute("UPDATE habits SET shared_id = NULL WHERE shared_id = ? AND user_id = ?", (shared_id, me))
    db.execute("DELETE FROM shared_members WHERE shared_id = ? AND user_id = ?", (shared_id, me))
    db.commit()
    flash("You left the group. Your history was kept as a personal habit.")
    return redirect(url_for("shared.index"))


@bp.route("/shared/<int:shared_id>/delete", methods=("POST",))
@login_required
def delete(shared_id):
    db = get_db()
    me = g.user["id"]
    shared = get_shared_or_404(db, shared_id, me)
    if shared["creator_id"] != me:
        abort(403)

    # ON DELETE CASCADE removes the memberships; ON DELETE SET NULL turns everyone's
    # copy into a normal personal habit, so nobody loses their history
    db.execute("DELETE FROM shared_habits WHERE id = ?", (shared_id,))
    db.commit()
    flash("Shared habit deleted. Everyone keeps their own history as a personal habit.")
    return redirect(url_for("shared.index"))

@bp.route("/shared/<int:shared_id>/members/<int:member_id>/remove", methods=("POST",))
@login_required
def remove_member(shared_id, member_id):
    """The creator can remove a member, or cancel an invitation that hasn't been answered."""
    db = get_db()
    me = g.user["id"]
    shared = get_shared_or_404(db, shared_id, me)
    if shared["creator_id"] != me:
        abort(403)
    if member_id == me:
        flash("You can't remove yourself. Delete the shared habit instead.")
        return redirect(url_for("shared.detail", shared_id=shared_id))

    member = db.execute(
        "SELECT status FROM shared_members WHERE shared_id = ? AND user_id = ?",
        (shared_id, member_id),
    ).fetchone()
    if member is None:
        abort(404)

    # Same rule as leaving: their history stays as a normal personal habit
    db.execute("UPDATE habits SET shared_id = NULL WHERE shared_id = ? AND user_id = ?", (shared_id, member_id))
    db.execute("DELETE FROM shared_members WHERE shared_id = ? AND user_id = ?", (shared_id, member_id))
    db.commit()
    flash("Invitation cancelled." if member["status"] == "invited" else "Member removed.")
    return redirect(url_for("shared.detail", shared_id=shared_id))