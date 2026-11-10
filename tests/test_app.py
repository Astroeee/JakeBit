"""Automated tests for Jakebit (the habit tracker).

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


def edit_profile(client, **extra):
    data = {"display_name": "", "bio": "", "accent": "theme", "banner": "mountain", "searchable": "on"}
    data.update(extra)
    return client.post("/profile/edit", data=data)


def save_settings(client, **extra):
    data = {"theme": "terracotta", "bg": "plain", "card": "soft", "fur": "red", "mascot_name": "Mochi"}
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
    assert b"Mark Complete" in alice.get("/").data
    complete(alice, hid)
    assert b"Undo" in alice.get("/").data and b"Mark Complete" not in alice.get("/").data
    complete(alice, hid)
    assert b"Mark Complete" in alice.get("/").data


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
    assert themes == {"alice": "graphite", "bob": "terracotta"}


def test_settings_reject_values_that_are_not_on_the_list(app, make_user):
    alice = make_user("alice")
    assert b"available options" in save_settings(alice, theme="hacker").data
    assert b"1 to 16" in save_settings(alice, mascot_name="x" * 17).data
    assert query(app, "SELECT theme FROM users")[0]["theme"] == "terracotta"


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
    """The stored picture(s): one row per user that has a picture."""
    return query(app, "SELECT data FROM avatar_images")


def test_upload_is_resized_to_a_square_jpeg(app, make_user):
    alice = make_user("alice")
    upload(alice, image_file(), "me.png")
    files = avatar_files(app)
    assert len(files) == 1
    with Image.open(io.BytesIO(files[0]["data"])) as saved:
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


def test_replacing_or_removing_a_picture_keeps_only_the_newest(app, make_user):
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
    edit_profile(alice, searchable="")            # opted out of friend search
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

# ------------------------------------------------------------------- weekly habits
WED = date(2026, 10, 14)   # a Wednesday; weeks run Monday to Sunday


@pytest.mark.parametrize("target, done, expected", [
    (3, {date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)}, (1, 1)),     # this week's goal already met
    (3, {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 12)}, (1, 1)),  # this week in progress
    (3, {date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 5), date(2026, 10, 6),
         date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)}, (1, 1)),     # a missed goal breaks the run
    (2, {date(2026, 9, 28), date(2026, 9, 29), date(2026, 10, 5), date(2026, 10, 6),
         date(2026, 10, 12), date(2026, 10, 13)}, (3, 3)),                          # three weeks in a row
    (1, {date(2026, 10, 6)}, (1, 1)),                                               # once a week, done last week
    (1, {date(2026, 9, 29), date(2026, 10, 13)}, (1, 1)),                           # skipped a whole week
    (2, {date(2026, 10, 13)}, (0, 0)),                                              # 1 of 2: nothing met yet
])
def test_weekly_streaks(target, done, expected):
    assert compute_streaks("weekly", done, WED, target) == expected


def test_weekly_rates_count_only_complete_weeks():
    from tracking import period_counts
    done = {date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 5), date(2026, 10, 6),
            date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)}
    assert period_counts("weekly", 3, done, date(2026, 9, 28), date(2026, 10, 18)) == (8, 9)
    assert period_counts("weekly", 3, done, date(2026, 9, 30), date(2026, 10, 18)) == (5, 6)   # partial first week skipped
    assert period_counts("weekly", 3, done, date(2026, 9, 28), date(2026, 10, 14)) == (5, 6)   # unfinished week not counted


def add_weekly(client, name="Gym", target=3):
    return client.post("/habits", data={"name": name, "category": "Fitness", "frequency": "weekly",
                                        "weekly_target": str(target)}, follow_redirects=True)


def test_weekly_habit_stores_its_goal_and_shows_progress(app, make_user):
    alice = make_user("alice")
    add_weekly(alice)
    assert query(app, "SELECT weekly_target FROM habits")[0]["weekly_target"] == 3
    assert "3× per week".encode() in alice.get("/habits").data
    complete(alice, habit_id(app, "Gym"))
    assert b"This week: 1 of 3" in alice.get("/").data
    assert alice.get("/statistics").status_code == 200
    assert alice.get("/calendar").status_code == 200


def test_weekly_goal_is_validated(app, make_user):
    alice = make_user("alice")
    assert b"1 and 7" in add_weekly(alice, target=9).data
    assert b"1 and 7" in add_weekly(alice, target="abc").data
    assert query(app, "SELECT COUNT(*) AS n FROM habits")[0]["n"] == 0
    alice.post("/habits", data={"name": "Run", "category": "Fitness", "frequency": "daily", "weekly_target": "5"})
    assert query(app, "SELECT weekly_target FROM habits")[0]["weekly_target"] == 1   # ignored for daily habits


def test_shared_weekly_habits_need_a_valid_weekly_goal(app, make_user):
    alice = make_user("alice")
    for bad in ("0", "9", "lots"):
        alice.post("/shared/create", data={"name": "Gym", "category": "Fitness", "frequency": "weekly", "weekly_target": bad})
    assert query(app, "SELECT COUNT(*) AS n FROM shared_habits")[0]["n"] == 0
    alice.post("/shared/create", data={"name": "Gym", "category": "Fitness", "frequency": "weekly", "weekly_target": "4"})
    assert query(app, "SELECT weekly_target FROM shared_habits")[0]["weekly_target"] == 4


def test_the_pixel_mascot_is_on_the_dashboard(make_user):
    assert b"px-bob" in make_user("alice").get("/").data


def test_pixel_mascot_renders_every_mood_and_survives_bad_input():
    import xml.etree.ElementTree as ET
    from pixelart import render_mascot
    for mood in ("happy", "cheer", "sleepy", "nonsense"):
        ET.fromstring(str(render_mascot(mood, 240)))
    assert "<svg" in str(render_mascot("happy", "huge"))

# --------------------------------------------------------------- password recovery
import re
CODE_RE = re.compile(r"[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}")
NEW_PW = "brand-new-pw1"


def get_code(client, password=PASSWORD):
    response = client.post("/settings/recovery", data={"password": password}, follow_redirects=True)
    return CODE_RE.search(response.data.decode()).group(0)


def reset(client, username, code, password=NEW_PW):
    return client.post("/reset-password", data={"username": username, "code": code,
                                                "password": password, "confirm": password},
                       follow_redirects=True)


def test_reset_with_a_recovery_code_and_the_code_works_only_once(app, make_user):
    alice = make_user("alice")
    code = get_code(alice)
    new_code = CODE_RE.search(reset(app.test_client(), "alice", code).data.decode()).group(0)
    assert new_code != code
    assert login(app.test_client(), "alice", NEW_PW).status_code == 302
    assert b"Incorrect" in login(app.test_client(), "alice", PASSWORD).data
    reset(app.test_client(), "alice", code, "other-new-pw1")                      # the old code is dead
    assert b"Incorrect" in login(app.test_client(), "alice", "other-new-pw1").data


def test_code_format_is_forgiving(app, make_user):
    alice = make_user("alice")
    code = get_code(alice)
    reset(app.test_client(), "alice", code.lower().replace("-", " "))
    assert login(app.test_client(), "alice", NEW_PW).status_code == 302


def test_wrong_codes_unknown_users_and_accounts_without_a_code_look_the_same(app, make_user):
    make_user("alice")                                                            # has no code yet
    for name in ("alice", "ghost"):
        response = reset(app.test_client(), name, "AAAA-AAAA-AAAA-AAAA")
        assert response.status_code == 200 and b"don&#39;t match" in response.data
    assert b"Incorrect" in login(app.test_client(), "alice", NEW_PW).data


def test_reset_attempts_are_rate_limited(app, make_user):
    make_user("alice")
    client = app.test_client()
    for _ in range(5):
        assert reset(client, "alice", "AAAA-AAAA-AAAA-AAAA").status_code == 200
    assert reset(client, "alice", "AAAA-AAAA-AAAA-AAAA").status_code == 429


def test_making_a_code_needs_your_password_and_it_is_stored_hashed(app, make_user):
    alice = make_user("alice")
    alice.post("/settings/recovery", data={"password": "wrong-pass-1"})
    assert query(app, "SELECT recovery_hash FROM users")[0]["recovery_hash"] is None
    code = get_code(alice)
    stored = query(app, "SELECT recovery_hash FROM users")[0]["recovery_hash"]
    assert stored and code.replace("-", "") not in stored
    assert alice.get("/recovery-code").status_code == 302                          # shown only once


def test_banner_asks_for_a_recovery_code_until_you_make_one(app, make_user):
    alice = make_user("alice")
    assert b"so you can reset your password" in alice.get("/").data
    get_code(alice)
    assert b"so you can reset your password" not in alice.get("/").data

# ------------------------------------------------------------------ custom days
MWF = 21   # Monday + Wednesday + Friday


@pytest.mark.parametrize("mask, done, expected", [
    (MWF, {date(2026, 10, 12), date(2026, 10, 14)}, (2, 2)),        # Mon + Wed done, Tuesday is a day off
    (MWF, {date(2026, 10, 9), date(2026, 10, 12)}, (2, 2)),         # Wednesday not done YET: streak survives
    (MWF, {date(2026, 10, 9), date(2026, 10, 14)}, (1, 1)),         # missed Monday breaks it
    (MWF, {date(2026, 10, 13)}, (0, 0)),                            # done on a day off: ignored
    (0, {date(2026, 10, 13)}, (0, 0)),                              # no days chosen: no streak, no endless loop
    (64, {date(2026, 10, 4), date(2026, 10, 11)}, (2, 2)),          # Sundays only
])
def test_custom_day_streaks(mask, done, expected):
    assert compute_streaks("custom", done, WED, 1, mask) == expected


def add_custom(client, name="Gym days", days=("0", "2", "4")):
    return client.post("/habits", data={"name": name, "category": "Fitness", "frequency": "custom",
                                        "days": list(days)}, follow_redirects=True)


def test_custom_days_are_saved_and_shown(app, make_user):
    alice = make_user("alice")
    add_custom(alice)
    assert query(app, "SELECT days_mask FROM habits")[0]["days_mask"] == MWF
    assert b"Mon, Wed, Fri" in alice.get("/habits").data


def test_custom_days_need_at_least_one_valid_day(app, make_user):
    alice = make_user("alice")
    for bad in ([], ["7"], ["x"]):
        assert b"at least one day" in add_custom(alice, days=bad).data
    assert query(app, "SELECT COUNT(*) AS n FROM habits")[0]["n"] == 0


def test_days_off_are_rest_days_on_the_dashboard(app, make_user):
    alice = make_user("alice")
    add_custom(alice, days=[str((date.today().weekday() + 1) % 7)])     # scheduled only for tomorrow's weekday
    assert b"Inactive on" in alice.get("/").data
    alice.post(f"/habits/{habit_id(app, 'Gym days')}/delete")
    add_custom(alice, name="Today habit", days=[str(date.today().weekday())])
    assert b"Inactive on" not in alice.get("/").data


def test_shared_custom_habits_need_at_least_one_day(app, make_user):
    alice = make_user("alice")
    alice.post("/shared/create", data={"name": "Gym", "category": "Fitness", "frequency": "custom"})
    assert query(app, "SELECT COUNT(*) AS n FROM shared_habits")[0]["n"] == 0


def test_dashboard_shows_the_pixel_nature_scenes(make_user):
    page = make_user("alice").get("/").data
    assert b"Your nature corner" in page and page.count(b'class="pixel scene"') == 3
    assert b"Jakebit" in page


def test_pixel_scenes_render_and_survive_bad_input():
    import xml.etree.ElementTree as ET
    from pixelscenes import render_scene
    for kind in ("mountain", "park", "forest"):
        for value in (0, 7, 100, 999):
            ET.fromstring(str(render_scene(kind, value)))
    assert "<svg" in str(render_scene("nope", "lots"))
    # the park blooms more flowers as progress goes up
    assert str(render_scene("park", 100)) != str(render_scene("park", 0))


def test_picture_is_served_from_the_database_and_cached_by_tag(app, make_user):
    alice = make_user("alice")
    upload(alice, image_file(), "me.png")
    uid = query(app, "SELECT id FROM users")[0]["id"]
    first = alice.get(f"/avatar/{uid}")
    assert first.mimetype == "image/jpeg" and first.data[:2] == b"\xff\xd8"
    again = alice.get(f"/avatar/{uid}", headers={"If-None-Match": first.headers["ETag"]})
    assert again.status_code == 304


def test_database_helpers_work_for_both_sqlite_and_postgres():
    from db import Row, to_pg
    row = Row((7, "alice"), ["id", "username"])
    assert row["id"] == 7 and row[1] == "alice" and len(row) == 2 and dict(row) == {"id": 7, "username": "alice"}
    assert to_pg("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = %s AND b = %s"
    assert to_pg("SELECT '100%' WHERE a = ?") == "SELECT '100%%' WHERE a = %s"


# --------------------------------------------------------------- profile pages
PROFILE_COLS = "display_name, bio, profile_accent, profile_banner, profile_widgets"


def test_profile_can_be_customised_and_widgets_follow_the_chosen_order(app, make_user):
    alice = make_user("alice")
    assert alice.get("/profile").status_code == 200
    response = edit_profile(alice, display_name="  Ali   Cat ", bio="Gym <b>rat</b>", accent="blue",
                            banner="forest", widget=["badges", "streak"])
    assert response.status_code == 302
    row = query(app, f"SELECT {PROFILE_COLS} FROM users")[0]
    assert (row["display_name"], row["profile_accent"], row["profile_banner"], row["profile_widgets"]) == \
        ("Ali Cat", "blue", "forest", "badges,streak")
    page = alice.get("/profile").data
    assert b"Ali Cat" in page and b"&lt;b&gt;rat" in page and b"<b>rat" not in page   # bio is escaped
    assert page.index(b"Achievements") < page.index(b"Streak records")
    assert b"pw-mascot" not in page                                                   # widget switched off


def test_profile_ignores_invalid_choices_and_limits_length(app, make_user):
    alice = make_user("alice")
    edit_profile(alice, display_name="x" * 80, bio="y" * 400, accent="evil", banner="../etc",
                 widget=["hack", "habits", "habits"])
    row = query(app, f"SELECT {PROFILE_COLS} FROM users")[0]
    assert len(row["display_name"]) == 30 and len(row["bio"]) == 160
    assert row["profile_accent"] == "theme" and row["profile_banner"] == "mountain"
    assert row["profile_widgets"] == "habits"


def test_friends_see_the_custom_profile_but_privacy_switches_still_apply(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    befriend(app, alice, bob, "bob")
    edit_profile(alice, display_name="Ali Cat", widget=["streak", "badges", "habits"])
    page = bob.get("/friends/alice").data
    assert b"Ali Cat" in page and b"@alice" in page and b"Streak records" in page
    save_settings(alice)                                         # scores switched off
    page = bob.get("/friends/alice").data
    assert b"Streak records" not in page and b"Achievements" not in page
    assert b"keeps their scores private" in page
    own = alice.get("/profile").data                             # the owner still sees everything
    assert b"Streak records" in own and b"Friends can" in own


def test_achievements_unlock_with_check_ins(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    assert alice.get("/profile").data.count(b"badge-tile locked") == 7
    complete(alice, habit_id(app))
    assert alice.get("/profile").data.count(b"badge-tile locked") == 6   # "First check-in" unlocked


def test_friend_search_shows_name_bio_and_respects_opt_out(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    edit_profile(alice, display_name="Alice from BJJ", bio="Blue belt")
    page = bob.get("/friends/search?q=alice").data
    assert b"Alice from BJJ" in page and b"Blue belt" in page and b"Add friend" in page
    assert b"Alice from BJJ" in bob.get("/friends/search?q=from bjj").data     # display name, any case
    assert b"at least 2" in bob.get("/friends/search?q=a").data
    assert b"Blue belt" not in bob.get("/friends/search?q=%25%25").data         # % is not a wildcard
    assert b"Add friend" not in alice.get("/friends/search?q=alice").data       # never lists yourself
    edit_profile(alice, display_name="Alice from BJJ", bio="Blue belt", searchable="")
    assert b"Blue belt" not in bob.get("/friends/search?q=alice").data


def test_scene_banner_is_cropped_to_a_strip():
    from pixelscenes import render_scene
    banner = str(render_scene("mountain", 3, banner=True))
    assert "preserveAspectRatio" in banner and 'viewBox="0 0 144 24"' in banner and "scale(-1 1)" in banner
    assert "preserveAspectRatio" not in str(render_scene("mountain", 3))


# ----------------------------------------------------- dashboard, month tracker, statistics
def test_dashboard_week_and_day_navigation_never_shows_the_future(app, make_user):
    from datetime import timedelta
    alice = make_user("alice")
    add_habit(alice)
    future = (date.today() + timedelta(days=30)).isoformat()
    page = alice.get(f"/?day={future}&week={future}")
    assert page.status_code == 200 and date.today().strftime("%a, %b %d").encode() in page.data
    assert alice.get("/?day=garbage&week=nope").status_code == 200
    older = (date.today() - timedelta(days=9)).isoformat()
    assert b"Current" in alice.get(f"/?week={older}").data          # a link back to this week


def test_past_days_can_be_logged_from_the_side_panel(app, make_user):
    from datetime import timedelta
    alice = make_user("alice")
    add_habit(alice)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    alice.post(f"/toggle/{habit_id(app)}", data={"date": yesterday, "next": f"/?day={yesterday}"})
    assert b"Undo" in alice.get(f"/?day={yesterday}").data
    assert b"Undo" not in alice.get("/").data                       # today is still open


def test_month_tracker_clamps_future_months_and_logs_cells(app, make_user):
    alice = make_user("alice")
    assert b"No active habits" in alice.get("/calendar").data
    add_habit(alice)
    page = alice.get("/calendar?month=2099-01")
    assert page.status_code == 200 and date.today().strftime("%B %Y").encode() in page.data
    assert alice.get("/calendar?month=garbage").status_code == 200
    alice.post(f"/toggle/{habit_id(app)}", data={"date": TODAY, "next": "/calendar"})
    assert query(app, "SELECT COUNT(*) AS n FROM habit_completions")[0]["n"] == 1


def test_statistics_ranges(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    complete(alice, habit_id(app))
    for span in ("week", "month", "year", "bogus"):
        page = alice.get(f"/statistics?range={span}")
        assert page.status_code == 200 and b"Habit Progress Over Time" in page.data and b"ttrack" in page.data


def test_week_grid_states_and_percentage():
    from datetime import timedelta
    from insights import week_grid
    monday = date(2026, 10, 12)
    habit = {"id": 1, "weekly": False, "frequency": "weekdays", "days_mask": 127, "target": 1,
             "created": date(2026, 1, 1), "done": {monday, monday + timedelta(days=1)}}
    rows, achieved = week_grid([habit], monday, today=monday + timedelta(days=3))
    states = [c["state"] for c in rows[0]["cells"]]
    assert states == ["done", "done", "miss", "today", "future", "off", "off"]
    assert (rows[0]["done"], rows[0]["need"], achieved) == (2, 5, 40)


def test_trend_bars_carry_percentages_and_mark_today():
    from insights import trend_bars
    bars = trend_bars([0, 50, 100], ["MON", "TUE", "WED"], today_index=2)
    assert [b["percent"] for b in bars] == [0, 50, 100] and [b["today"] for b in bars] == [False, False, True]
    assert trend_bars([], []) == []


# ------------------------------------------------------------------ habit emoji logos
def test_habit_can_get_an_emoji_logo_and_it_shows_up(app, make_user):
    alice = make_user("alice")
    alice.post("/habits", data={"name": "Water", "category": "Health", "frequency": "daily", "icon": "🏋️"})
    assert query(app, "SELECT icon FROM habits")[0]["icon"] == "🏋️"
    assert "🏋️".encode() in alice.get("/").data and "🏋️".encode() in alice.get("/habits").data


def test_unknown_logos_are_ignored_and_auto_uses_the_category_icon(app, make_user):
    alice = make_user("alice")
    alice.post("/habits", data={"name": "Water", "category": "Health", "frequency": "daily", "icon": "<script>"})
    assert query(app, "SELECT icon FROM habits")[0]["icon"] is None
    assert "💧".encode() in alice.get("/").data                    # the Health category's icon


def test_logo_can_be_changed_and_reset_when_editing(app, make_user):
    alice = make_user("alice")
    add_habit(alice)
    hid = habit_id(app)
    form = {"name": HABIT, "category": "Health", "frequency": "daily"}
    alice.post(f"/habits/{hid}/edit", data={**form, "icon": "🎸"})
    assert query(app, "SELECT icon FROM habits")[0]["icon"] == "🎸"
    assert "value=\"🎸\" checked".encode() in alice.get(f"/habits/{hid}/edit").data      # picker remembers it
    alice.post(f"/habits/{hid}/edit", data={**form, "icon": ""})
    assert query(app, "SELECT icon FROM habits")[0]["icon"] is None


def test_retired_themes_show_as_their_closest_replacement(app, make_user):
    alice = make_user("alice")
    for old, new in (("forest", "sage"), ("oceannight", "midnight"), ("purple", "terracotta")):
        with app.app_context():
            conn = database.get_db()
            conn.execute("UPDATE users SET theme = ?", (old,))
            conn.commit()
        assert f'data-theme="{new}"'.encode() in alice.get("/").data


# --------------------------------------------------------------- editing group habits
def joined_group(app, alice, bob):
    """alice creates 'Morning run' and bob accepts the invitation, so both have a copy."""
    sid = make_group(app, alice, bob)
    bob.post(f"/shared/{sid}/accept")
    return sid


def own_habit(app, username):
    return query(app, "SELECT id, name, category, frequency, icon FROM habits WHERE user_id = ?", (user_id(app, username),))[0]


def test_creator_can_edit_a_group_habit_for_everyone(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    sid = joined_group(app, alice, bob)
    response = alice.post(f"/habits/{own_habit(app, 'alice')['id']}/edit",
                          data={"name": "Run at dawn", "category": "Health", "frequency": "weekdays", "icon": "🏃"})
    assert response.status_code == 302 and f"/shared/{sid}" in response.headers["Location"]
    assert query(app, "SELECT name, frequency FROM shared_habits")[0]["name"] == "Run at dawn"
    bobs = own_habit(app, "bob")
    assert (bobs["name"], bobs["category"], bobs["frequency"], bobs["icon"]) == ("Run at dawn", "Health", "weekdays", None)
    assert own_habit(app, "alice")["icon"] == "🏃"                 # logos stay personal


def test_other_members_can_only_change_their_own_logo(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    joined_group(app, alice, bob)
    bob.post(f"/habits/{own_habit(app, 'bob')['id']}/edit", data={"name": "Hacked", "frequency": "weekdays", "icon": "🎸"})
    assert query(app, "SELECT name FROM shared_habits")[0]["name"] == "Morning run"
    assert own_habit(app, "alice")["name"] == "Morning run"
    assert (own_habit(app, "bob")["name"], own_habit(app, "bob")["icon"]) == ("Morning run", "🎸")


def test_group_habits_can_become_weekly_or_custom_for_everyone(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    joined_group(app, alice, bob)
    alice_id = own_habit(app, "alice")["id"]
    form = {"name": "Morning run", "category": "Fitness"}
    alice.post(f"/habits/{alice_id}/edit", data={**form, "frequency": "weekly", "weekly_target": "3"})
    shared = query(app, "SELECT frequency, weekly_target FROM shared_habits")[0]
    assert (shared["frequency"], shared["weekly_target"]) == ("weekly", 3)
    bobs = query(app, "SELECT frequency, weekly_target FROM habits WHERE user_id = ?", (user_id(app, "bob"),))[0]
    assert (bobs["frequency"], bobs["weekly_target"]) == ("weekly", 3)
    alice.post(f"/habits/{alice_id}/edit", data={**form, "frequency": "custom", "days": ["0", "2", "4"]})
    assert query(app, "SELECT frequency, days_mask FROM shared_habits")[0]["days_mask"] == 0b10101
    assert query(app, "SELECT days_mask FROM habits WHERE user_id = ?", (user_id(app, "bob"),))[0]["days_mask"] == 0b10101


def test_group_schedule_must_be_valid(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    joined_group(app, alice, bob)
    alice.post(f"/habits/{own_habit(app, 'alice')['id']}/edit",
               data={"name": "Morning run", "category": "Fitness", "frequency": "custom"})   # no days chosen
    assert query(app, "SELECT frequency FROM shared_habits")[0]["frequency"] == "daily"


def test_new_group_habits_can_start_weekly_or_custom_and_new_members_get_the_schedule(app, make_user):
    alice, bob = make_user("alice"), make_user("bob")
    befriend(app, alice, bob, "bob")
    alice.post("/shared/create", data={"name": "Gym", "category": "Fitness", "frequency": "weekly",
                                       "weekly_target": "2", "invite": [str(user_id(app, "bob"))]})
    sid = query(app, "SELECT id FROM shared_habits")[0]["id"]
    bob.post(f"/shared/{sid}/accept")
    for who in ("alice", "bob"):
        row = query(app, "SELECT frequency, weekly_target FROM habits WHERE user_id = ?", (user_id(app, who),))[0]
        assert (row["frequency"], row["weekly_target"]) == ("weekly", 2)
    assert b"This week: 0 of 2" in alice.get(f"/shared/{sid}").data
    alice.post("/shared/create", data={"name": "Yoga", "category": "Fitness", "frequency": "custom", "days": ["1", "3"]})
    assert query(app, "SELECT days_mask FROM shared_habits WHERE name = 'Yoga'")[0]["days_mask"] == 0b1010


def test_group_streak_counts_weeks_only_when_everyone_reached_the_goal():
    from shared import group_streaks
    monday = date(2026, 10, 12)                       # a Monday
    today = monday + timedelta(days=3)
    two = lambda week: {monday + timedelta(days=7 * week), monday + timedelta(days=7 * week + 1)}
    shared = {"frequency": "weekly", "weekly_target": 2, "days_mask": 127}
    both = [two(-2) | two(-1), two(-2) | two(-1)]
    assert group_streaks(shared, both, today)[0] == 2
    one_slacker = [two(-2) | two(-1), two(-2)]                    # second member missed last week
    current, longest = group_streaks(shared, one_slacker, today)
    assert current == 0 and longest == 1
    assert group_streaks(shared, [], today) == (0, 0)


def test_habit_form_shows_frequency_tiles(app, make_user):
    alice = make_user("alice")
    page = alice.get("/habits").data
    assert b'class="freq-tile"' in page and b"data-weekly-target" in page and b"data-custom-days" in page


def test_profile_colours_follow_the_theme_unless_an_accent_is_chosen(app, make_user):
    alice = make_user("alice")
    assert b"--accent: var(--purple)" in alice.get("/profile").data           # the theme's colour
    edit_profile(alice, accent="blue")
    assert b"--accent: #1f5fd6" in alice.get("/profile").data                 # a fixed accent
    edit_profile(alice, accent="theme")
    assert b"--accent: var(--purple)" in alice.get("/profile").data


# ------------------------------------------------------------------------ installable app
def test_manifest_makes_the_site_installable(app):
    response = app.test_client().get("/manifest.webmanifest")
    assert response.status_code == 200 and response.mimetype == "application/manifest+json"
    data = response.get_json()
    assert (data["name"], data["display"], data["start_url"]) == ("Jakebit", "standalone", "/")
    assert {"192x192", "512x512"} <= {i["sizes"] for i in data["icons"]}
    assert any(i["purpose"] == "maskable" for i in data["icons"])


def test_every_icon_in_the_manifest_exists_with_the_right_size(app):
    client = app.test_client()
    for icon in client.get("/manifest.webmanifest").get_json()["icons"]:
        response = client.get(icon["src"])
        assert response.status_code == 200
        with Image.open(io.BytesIO(response.data)) as image:
            assert f"{image.width}x{image.height}" == icon["sizes"]


def test_service_worker_is_served_from_the_root_and_never_stored(app):
    response = app.test_client().get("/sw.js")
    assert response.status_code == 200 and "javascript" in response.mimetype
    assert response.headers["Service-Worker-Allowed"] == "/" and response.headers["Cache-Control"] == "no-cache"
    assert b"/offline" in response.data and b'request.method !== "GET"' in response.data


def test_offline_page_works_without_logging_in(app):
    page = app.test_client().get("/offline")
    assert page.status_code == 200 and b"offline" in page.data


def test_pages_link_the_manifest_and_app_icons(app, make_user):
    page = make_user("alice").get("/").data
    assert b'rel="manifest"' in page and b"apple-touch-icon" in page and b"data-install" in page
