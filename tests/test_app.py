"""Automated tests for the Habit Tracker.

Run them from the project folder with:   pytest
Every test gets its OWN fresh temporary database (see conftest.py), so the tests
never touch your real data and never affect each other.
"""
import io
import os
import sqlite3
from datetime import date, timedelta

import pytest
from PIL import Image

import db as database
from tracking import compute_streaks

PASSWORD = "password123"
TODAY = date.today().isoformat()
HABIT = "Drink water"   # (the Habits page has "Read 20 minutes" as placeholder text, so we avoid that name)
PAGES = ["/", "/habits", "/calendar", "/statistics", "/friends", "/shared", "/settings"]


# ---------------------------------------------------------------- helpers
def register(client, username="alice", password=PASSWORD, email=None, confirm=None):
    return client.post("/register", data={
        "username": username,
        "email": email or f"{username}@example.com",
        "password": password,
        "confirm": password if confirm is None else confirm,
    })


def login(client, username="alice", password=PASSWORD, url="/login"):
    return client.post(url, data={"username": username, "password": password})


def query(app, sql, params=()):
    """Run a SELECT directly against the test database."""
    with app.app_context():
        return database.get_db().execute(sql, params).fetchall()


def user_id(app, username):
    return query(app, "SELECT id FROM users WHERE username = ?", (username,))[0]["id"]


def add_habit(client, name=HABIT, category="Learning", frequency="daily"):
    return client.post("/habits", data={"name": name, "category": category, "frequency": frequency},
                       follow_redirects=True)


def habit_id(app, name=HABIT, username="alice"):
    rows = query(app, "SELECT id FROM habits WHERE name = ? AND user_id = ?", (name, user_id(app, username)))
    return rows[0]["id"]


def complete(client, hid, day=TODAY):
    """Tick a habit for a day (ticking it again un-ticks it)."""
    return client.post(f"/toggle/{hid}", data={"date": day})


def befriend(app, requester, addressee, addressee_name):
    requester.post("/friends/add", data={"username": addressee_name})
    friendship = query(app, "SELECT id FROM friendships ORDER BY id DESC LIMIT 1")[0]["id"]
    addressee.post(f"/friends/{friendship}/accept")


def save_settings(client, **extra):
    data = {"theme": "purple", "bg": "plain", "card": "soft", "fur": "red", "mascot_name": "Mochi"}
    data.update(extra)  # checkboxes (show_scores, show_habit_names) only count when included
    return client.post("/settings", data=data, follow_redirects=True)


def image_file(fmt="PNG", size=(400, 300)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, fmt)
    buffer.seek(0)
    return buffer


def upload(client, fileobj, filename):
    return client.post("/settings/avatar", data={"avatar": (fileobj, filename)},
                       content_type="multipart/form-data", follow_redirects=True)


def make_group(app, alice, bob):
    """alice and bob become friends, then alice creates 'Morning run' and invites bob."""
    befriend(app, alice, bob, "bob")
    alice.post("/shared/create", data={
        "name": "Morning run", "category": "Fitness", "frequency": "daily",
        "invite": [str(user_id(app, "bob"))]})
    return query(app, "SELECT id FROM shared_habits")[0]["id"]


# ------------------------------------------------- streak logic (no web app needed)
D = date(2026, 10, 12)  # a Monday


def days_ago(n):
    return D - timedelta(days=n)


@pytest.mark.parametrize("frequency, done, expected", [
    ("daily", set(), (0, 0)),                                          # nothing done
    ("daily", {days_ago(0), days_ago(1), days_ago(2)}, (3, 3)),        # three days in a row
    ("daily", {days_ago(1), days_ago(2)}, (2, 2)),                     # today not done YET: streak survives
    ("daily", {days_ago(0), days_ago(2)}, (1, 1)),                     # a gap breaks the streak
    ("daily", {days_ago(0)} | {days_ago(i) for i in range(6, 11)}, (1, 5)),  # longest > current
    ("daily", {days_ago(5)}, (0, 1)),                                  # old completion, no current streak
    ("weekdays", {date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)}, (3, 3)),  # weekend skipped
    ("daily", {date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)}, (1, 2)),     # same days, daily habit
])
def test_streaks(frequency, done, expected):
    assert compute_streaks(frequency, done, D) == expected


# --------------------------------------------------------------- accounts and login
def test_register_stores_a_hash_not_the_password(app):
    client = app.test_client()
    assert register(client).status_code == 302
    stored = query(app, "SELECT password_hash FROM users")[0]["password_hash"]
    assert stored != PASSWORD and PASSWORD not in stored


@pytest.mark.parametrize("username, email, password, confirm, message", [
    ("ab", "a@example.com", PASSWORD, PASSWORD, b"Username must be"),
    ("alice", "not-an-email", PASSWORD, PASSWORD, b"valid email"),
    ("alice", "a@example.com", "short", "short", b"at least 8"),
    ("alice", "a@example.com", PASSWORD, "different1", b"match"),
])
def test_register_rejects_bad_input(app, username, email, password, confirm, message):
    response = register(app.test_client(), username, password, email, confirm)
    assert response.status_code == 200 and message in response.data
    assert query(app, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 0


def test_usernames_are_unique_ignoring_case(app):
    client = app.test_client()
    register(client, "alice")
    assert b"already taken" in register(client, "ALICE", email="other@example.com").data
    assert b"already taken" in register(client, "bob", email="alice@example.com").data


def test_login_with_username_or_email(app):
    register(app.test_client(), "alice")
    assert login(app.test_client(), "alice").status_code == 302
    assert login(app.test_client(), "alice@example.com").status_code == 302


def test_wrong_password_and_unknown_user_get_the_same_message(app):
    register(app.test_client(), "alice")
    wrong_password = login(app.test_client(), "alice", "nope-nope-1")
    unknown_user = login(app.test_client(), "nobody", "nope-nope-1")
    assert b"Incorrect username or password" in wrong_password.data
    assert b"Incorrect username or password" in unknown_user.data


def test_login_cannot_redirect_to_another_website(app):
    register(app.test_client(), "alice")
    response = login(app.test_client(), "alice", url="/login?next=//evil.com")
    assert response.status_code == 302 and "evil.com" not in response.headers["Location"]


def test_logout_ends_the_session(app, make_user):
    alice = make_user("alice")
    assert alice.get("/").status_code == 200
    assert alice.post("/logout").status_code == 302
    assert alice.get("/").status_code == 302


@pytest.mark.parametrize("url", PAGES)
def test_pages_require_login(app, url):
    response = app.test_client().get(url)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("url", PAGES)
def test_pages_load_when_logged_in(make_user, url):
    assert make_user("alice").get(url).status_code == 200


def test_csrf_protection_blocks_forms_without_a_token(csrf_app):
    response = csrf_app.test_client().post("/login", data={"username": "alice", "password": PASSWORD})
    assert response.status_code == 400


# ------------------------------------------------------------------------ habits
def test_add_habit(make_user):
    alice = make_user("alice")
    assert HABIT.encode() in add_habit(alice).data


@pytest.mark.parametrize("name, category, frequency, message", [
    ("", "Health", "daily", b"required"),
    ("x" * 101, "Health", "daily", b"100 characters"),
    ("Run", "Nonsense", "daily", b"valid category"),
    ("Run", "Health", "hourly", b"valid frequency"),
])
def test_habit_validation(app, make_user, name, category, frequency, message):
    alice = make_user("alice")
    assert message in add_habit(alice, name, category, frequency).data
    assert query(app, "SELECT COUNT(*) AS n FROM habits")[0]["n"] == 0


def test_edit_habit(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    response = alice.post(f"/habits/{hid}/edit", data={"name": "Study hard", "category": "Learning",
                                                      "frequency": "weekdays"}, follow_redirects=True)
    assert b"Study hard" in response.data and HABIT.encode() not in response.data


def test_paused_habit_disappears_from_the_dashboard(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    assert HABIT.encode() in alice.get("/").data
    alice.post(f"/habits/{hid}/toggle-active")
    assert HABIT.encode() not in alice.get("/").data
    assert b"Paused" in alice.get("/habits").data
    alice.post(f"/habits/{hid}/toggle-active")           # activate again
    assert HABIT.encode() in alice.get("/").data


def test_delete_habit(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    alice.post(f"/habits/{habit_id(app)}/delete")
    assert query(app, "SELECT COUNT(*) AS n FROM habits")[0]["n"] == 0


def test_nobody_can_touch_someone_elses_habit(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    add_habit(alice)
    hid = habit_id(app)
    edit = bob.post(f"/habits/{hid}/edit", data={"name": "Hacked", "category": "Health", "frequency": "daily"})
    assert edit.status_code == 404
    assert bob.post(f"/habits/{hid}/toggle-active").status_code == 404
    assert bob.post(f"/habits/{hid}/delete").status_code == 404
    assert query(app, "SELECT name FROM habits")[0]["name"] == HABIT


# ----------------------------------------------------------------- completions
def test_tick_and_untick_a_habit(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    assert b"Mark as done" in alice.get("/").data
    complete(alice, hid)
    assert b"tap to undo" in alice.get("/").data
    complete(alice, hid)
    assert b"Mark as done" in alice.get("/").data


def test_can_log_a_past_day_but_not_the_future(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert complete(alice, hid, yesterday).status_code == 302
    assert complete(alice, hid, tomorrow).status_code == 400
    assert complete(alice, hid, "not-a-date").status_code == 400
    assert query(app, "SELECT COUNT(*) AS n FROM habit_completions")[0]["n"] == 1


def test_cannot_tick_someone_elses_habit(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    add_habit(alice)
    assert complete(bob, habit_id(app)).status_code == 404


def test_database_itself_blocks_duplicate_completions(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    sql = "INSERT INTO habit_completions (habit_id, completion_date) VALUES (?, ?)"
    with app.app_context():
        conn = database.get_db()
        conn.execute(sql, (hid, "2026-01-01"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, (hid, "2026-01-01"))


def test_tick_cannot_redirect_to_another_website(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    response = alice.post(f"/toggle/{habit_id(app)}", data={"date": TODAY, "next": "//evil.com"})
    assert "evil.com" not in response.headers["Location"]


def test_statistics_page_shows_numbers(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    complete(alice, habit_id(app))
    response = alice.get("/statistics")
    assert response.status_code == 200 and b"Completion rate" in response.data


# ----------------------------------------------------------------------- settings
def test_settings_are_saved_per_account(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    save_settings(alice, theme="graphite", mascot_name="Biscuit")
    themes = {r["username"]: r["theme"] for r in query(app, "SELECT username, theme FROM users")}
    assert themes == {"alice": "graphite", "bob": "purple"}


def test_settings_reject_values_that_are_not_on_the_list(app, make_user):
    alice = make_user("alice")
    assert b"available options" in save_settings(alice, theme="hacker").data
    assert b"1 to 16" in save_settings(alice, mascot_name="x" * 17).data
    assert query(app, "SELECT theme FROM users")[0]["theme"] == "purple"


# ------------------------------------------------------------------------ friends
def test_friend_request_flow_and_leaderboard(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    assert b"request sent" in alice.post("/friends/add", data={"username": "bob"}, follow_redirects=True).data
    assert b"Requests for you" in bob.get("/friends").data
    fid = query(app, "SELECT id FROM friendships")[0]["id"]
    bob.post(f"/friends/{fid}/accept")
    board = alice.get("/friends").data
    assert b"alice (you)" in board and b"bob" in board


def test_cannot_add_yourself_or_a_stranger_who_does_not_exist(make_user):
    alice = make_user("alice")
    assert b"add yourself" in alice.post("/friends/add", data={"username": "alice"}, follow_redirects=True).data
    assert b"No user" in alice.post("/friends/add", data={"username": "ghost"}, follow_redirects=True).data


def test_only_the_receiver_can_accept(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    alice.post("/friends/add", data={"username": "bob"})
    fid = query(app, "SELECT id FROM friendships")[0]["id"]
    assert alice.post(f"/friends/{fid}/accept").status_code == 404
    assert bob.post(f"/friends/{fid}/accept").status_code == 302


def test_friend_profiles_are_for_friends_only(app, make_user):
    alice, bob, carol = make_user("alice"), make_user("bob"), make_user("carol")
    assert bob.get("/friends/alice").status_code == 404
    befriend(app, alice, bob, "bob")
    assert bob.get("/friends/alice").status_code == 200
    assert carol.get("/friends/alice").status_code == 404


def test_privacy_switches_control_what_friends_see(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    add_habit(alice, name="SecretHabit")
    befriend(app, alice, bob, "bob")

    profile = bob.get("/friends/alice").data                      # defaults: scores on, names off
    assert b"SecretHabit" not in profile and b"share their habit names" in profile

    save_settings(alice, show_scores="on", show_habit_names="on")
    assert b"SecretHabit" in bob.get("/friends/alice").data

    save_settings(alice)                                           # both switches off
    profile = bob.get("/friends/alice").data
    assert b"SecretHabit" not in profile and b"keeps their scores private" in profile
    assert b"Scores are private" in bob.get("/friends").data


# ------------------------------------------------------------------ shared habits
def test_invited_people_must_accept_before_they_can_see_the_group(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    assert b"Morning run" in bob.get("/shared").data               # the invitation
    assert bob.get(f"/shared/{sid}").status_code == 404            # but not the group itself
    bob.post(f"/shared/{sid}/accept")
    assert bob.get(f"/shared/{sid}").status_code == 200
    assert len(query(app, "SELECT id FROM habits WHERE shared_id = ?", (sid,))) == 2


def test_strangers_get_a_404_for_a_group(app, make_user):
    alice, bob, carol = make_user("alice"), make_user("bob"), make_user("carol")
    sid = make_group(app, alice, bob)
    assert carol.get(f"/shared/{sid}").status_code == 404


def test_can_only_invite_your_own_friends(app, make_user):
    alice, carol = make_user("alice"), make_user("carol")
    response = alice.post("/shared/create", data={
        "name": "Morning run", "category": "Fitness", "frequency": "daily",
        "invite": [str(user_id(app, "carol"))]}, follow_redirects=True)
    assert b"your friends" in response.data
    assert query(app, "SELECT COUNT(*) AS n FROM shared_habits")[0]["n"] == 0


def test_group_streak_needs_everyone(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    bob.post(f"/shared/{sid}/accept")
    complete(alice, habit_id(app, "Morning run", "alice"))
    assert b"1/2" in alice.get(f"/shared/{sid}").data
    complete(bob, habit_id(app, "Morning run", "bob"))
    assert b"2/2" in alice.get(f"/shared/{sid}").data


def test_shared_habits_are_managed_from_the_group_page(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    hid = habit_id(app, "Morning run", "alice")
    response = alice.post(f"/habits/{hid}/delete")
    assert response.status_code == 302 and f"/shared/{sid}" in response.headers["Location"]
    assert query(app, "SELECT COUNT(*) AS n FROM habits WHERE id = ?", (hid,))[0]["n"] == 1


def test_leaving_keeps_your_history_as_a_personal_habit(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    bob.post(f"/shared/{sid}/accept")
    bob.post(f"/shared/{sid}/leave")
    copy = query(app, "SELECT shared_id FROM habits WHERE user_id = ?", (user_id(app, "bob"),))
    assert len(copy) == 1 and copy[0]["shared_id"] is None
    assert bob.get(f"/shared/{sid}").status_code == 404


def test_only_the_creator_can_delete_and_the_creator_cannot_leave(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    bob.post(f"/shared/{sid}/accept")
    assert bob.post(f"/shared/{sid}/delete").status_code == 403
    assert b"creator" in alice.post(f"/shared/{sid}/leave", follow_redirects=True).data
    alice.post(f"/shared/{sid}/delete")
    assert query(app, "SELECT COUNT(*) AS n FROM shared_habits")[0]["n"] == 0
    remaining = query(app, "SELECT shared_id FROM habits")          # everyone keeps a personal copy
    assert len(remaining) == 2 and all(r["shared_id"] is None for r in remaining)


# --------------------------------------------------------------- profile pictures
def avatar_files(app):
    folder = app.config["AVATAR_FOLDER"]
    return os.listdir(folder) if os.path.exists(folder) else []


def test_upload_is_resized_to_a_square_jpeg(app, make_user):
    alice = make_user("alice")
    upload(alice, image_file(), "me.png")
    files = avatar_files(app)
    assert len(files) == 1
    with Image.open(os.path.join(app.config["AVATAR_FOLDER"], files[0])) as saved:
        assert saved.size == (256, 256) and saved.format == "JPEG"


def test_fake_and_unsupported_files_are_rejected(app, make_user):
    alice = make_user("alice")
    assert b"valid JPG" in upload(alice, io.BytesIO(b"definitely not an image"), "evil.jpg").data
    assert b"valid JPG" in upload(alice, image_file("GIF"), "animated.gif").data
    assert avatar_files(app) == []
    assert query(app, "SELECT avatar FROM users")[0]["avatar"] is None


def test_files_over_5mb_are_rejected(app, make_user):
    alice = make_user("alice")
    assert b"too big" in upload(alice, io.BytesIO(b"0" * (6 * 1024 * 1024)), "big.png").data
    assert avatar_files(app) == []


def test_replacing_or_removing_a_picture_deletes_the_old_file(app, make_user):
    alice = make_user("alice")
    upload(alice, image_file(), "one.png")
    upload(alice, image_file(size=(300, 300)), "two.png")
    assert len(avatar_files(app)) == 1
    alice.post("/settings/avatar/remove")
    assert avatar_files(app) == []
    assert query(app, "SELECT avatar FROM users")[0]["avatar"] is None


def test_pictures_are_only_visible_to_friends_and_yourself(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    upload(alice, image_file(), "me.png")
    alice_id = user_id(app, "alice")
    assert alice.get(f"/avatar/{alice_id}").mimetype == "image/jpeg"
    assert bob.get(f"/avatar/{alice_id}").mimetype == "image/svg+xml"   # stranger: placeholder only
    befriend(app, alice, bob, "bob")
    assert bob.get(f"/avatar/{alice_id}").mimetype == "image/jpeg"


def test_pictures_require_login(app):
    assert app.test_client().get("/avatar/1").status_code == 302

def test_production_refuses_the_development_secret_key(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app({"DATABASE": str(tmp_path / "t.db")})

# ------------------------------------------ rate limiting, badges, group management
def insert_users(app, count):
    """Create users straight in the database (registering this many would hit the sign-up limit)."""
    with app.app_context():
        conn = database.get_db()
        for i in range(count):
            conn.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                         (f"user{i:02d}", f"user{i:02d}@example.com", "x"))
        conn.commit()


def test_login_locks_after_repeated_failures_then_unlocks(app, monkeypatch):
    import ratelimit
    register(app.test_client(), "alice")
    client = app.test_client()
    for _ in range(5):
        assert login(client, "alice", "wrong-pass-1").status_code == 200
    blocked = login(client, "alice", PASSWORD)           # even the CORRECT password is refused now
    assert blocked.status_code == 429 and b"Too many" in blocked.data
    later = ratelimit.now() + 16 * 60                    # pretend 16 minutes have passed
    monkeypatch.setattr(ratelimit, "now", lambda: later)
    assert login(client, "alice", PASSWORD).status_code == 302


def test_a_successful_login_resets_the_failure_count(app):
    register(app.test_client(), "alice")
    client = app.test_client()
    for _ in range(4):
        login(client, "alice", "wrong-pass-1")
    assert login(client, "alice", PASSWORD).status_code == 302
    client.post("/logout")
    for _ in range(4):
        login(client, "alice", "wrong-pass-1")
    assert login(client, "alice", PASSWORD).status_code == 302   # the counter started over


def test_signups_are_limited_per_network(app):
    client = app.test_client()
    for i in range(10):
        assert register(client, f"user{i:02d}").status_code == 302
    assert register(client, "user99").status_code == 429


def test_friend_requests_are_limited_per_hour(app, make_user):
    alice = make_user("alice")
    insert_users(app, 21)
    for i in range(20):
        alice.post("/friends/add", data={"username": f"user{i:02d}"})
    response = alice.post("/friends/add", data={"username": "user20"}, follow_redirects=True)
    assert b"too quickly" in response.data
    assert query(app, "SELECT COUNT(*) AS n FROM friendships")[0]["n"] == 20


def test_client_ip_uses_x_real_ip_only_behind_the_proxy(app):
    import ratelimit
    with app.test_request_context("/", headers={"X-Real-IP": "9.9.9.9"}, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        assert ratelimit.client_ip() == "10.0.0.1"       # not trusted by default
        app.config["TRUST_X_REAL_IP"] = True
        assert ratelimit.client_ip() == "9.9.9.9"


def test_migrations_are_safe_to_run_repeatedly(app):
    with app.app_context():
        database.run_migrations()
        assert database.run_migrations() == []


def test_nav_badges_count_pending_requests_and_invitations(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    assert b'class="badge"' not in bob.get("/").data
    alice.post("/friends/add", data={"username": "bob"})
    assert b'class="badge"' in bob.get("/").data                  # friend request waiting
    fid = query(app, "SELECT id FROM friendships")[0]["id"]
    bob.post(f"/friends/{fid}/accept")
    assert b'class="badge"' not in bob.get("/").data              # answered, so the badge is gone
    alice.post("/shared/create", data={"name": "Morning run", "category": "Fitness", "frequency": "daily",
                                       "invite": [str(user_id(app, "bob"))]})
    assert b'class="badge"' in bob.get("/").data                  # invitation waiting


def test_creator_can_remove_a_member_and_they_keep_their_history(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)
    bob.post(f"/shared/{sid}/accept")
    bob_id = user_id(app, "bob")
    assert alice.post(f"/shared/{sid}/members/{bob_id}/remove").status_code == 302
    copy = query(app, "SELECT shared_id FROM habits WHERE user_id = ?", (bob_id,))
    assert len(copy) == 1 and copy[0]["shared_id"] is None
    assert bob.get(f"/shared/{sid}").status_code == 404


def test_creator_can_cancel_a_pending_invitation(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = make_group(app, alice, bob)                              # bob is invited but hasn't joined
    bob_id = user_id(app, "bob")
    alice.post(f"/shared/{sid}/members/{bob_id}/remove")
    assert query(app, "SELECT COUNT(*) AS n FROM shared_members WHERE user_id = ?", (bob_id,))[0]["n"] == 0
    assert bob.post(f"/shared/{sid}/accept").status_code == 404    # the invitation is gone


def test_only_the_creator_can_remove_people_and_not_themselves(app, make_user):
    alice, bob, carol = make_user("alice"), make_user("bob"), make_user("carol")
    befriend(app, alice, bob, "bob")
    befriend(app, alice, carol, "carol")
    alice.post("/shared/create", data={"name": "Morning run", "category": "Fitness", "frequency": "daily",
                                       "invite": [str(user_id(app, "bob")), str(user_id(app, "carol"))]})
    sid = query(app, "SELECT id FROM shared_habits")[0]["id"]
    bob.post(f"/shared/{sid}/accept")
    carol.post(f"/shared/{sid}/accept")
    assert bob.post(f"/shared/{sid}/members/{user_id(app, 'carol')}/remove").status_code == 403
    alice.post(f"/shared/{sid}/members/{user_id(app, 'alice')}/remove")
    assert len(query(app, "SELECT user_id FROM shared_members WHERE shared_id = ?", (sid,))) == 3