"""Shared test setup. pytest automatically loads this file before running any tests."""
import pytest
import db as database
from app import create_app


def make_test_app(tmp_path, csrf=False):
    """Build a brand-new app that uses a temporary database and a temporary avatar folder."""
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "DATABASE": str(tmp_path / "test.db"),
        "AVATAR_FOLDER": str(tmp_path / "avatars"),
        "WTF_CSRF_ENABLED": csrf,   # off for most tests so forms are easy to post; one test turns it on
    })
    with app.app_context():
        database.init_db()          # creates the tables from schema.sql in the temporary database
    return app


@pytest.fixture
def app(tmp_path):
    """A fresh app and empty database for every single test (tmp_path is unique per test)."""
    return make_test_app(tmp_path)


@pytest.fixture
def csrf_app(tmp_path):
    """Same as `app`, but with CSRF protection switched on."""
    return make_test_app(tmp_path, csrf=True)


@pytest.fixture
def make_user(app):
    """Returns a function that registers + logs in a user and hands back THEIR OWN browser.
    Two users = two separate clients, just like two people on two devices."""
    def _make(username):
        client = app.test_client()
        client.post("/register", data={
            "username": username, "email": f"{username}@example.com",
            "password": "password123", "confirm": "password123"})
        client.post("/login", data={"username": username, "password": "password123"})
        return client
    return _make