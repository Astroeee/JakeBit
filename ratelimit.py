import time
from flask import current_app, request


def now():
    """The current time. It's a function so tests can fake the clock."""
    return time.time()


def client_ip():
    """The visitor's IP address.
    On PythonAnywhere, remote_addr is the load balancer, and the real visitor is in the
    X-Real-IP header. We only trust that header when TRUST_X_REAL_IP is on (production),
    because anyone can send a fake header to a server that has no balancer in front of it."""
    if current_app.config.get("TRUST_X_REAL_IP"):
        return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"
    return request.remote_addr or "unknown"


def too_many(db, scope, limit, window):
    """True if `scope` (like 'login:ip:1.2.3.4') already had `limit` or more events
    in the last `window` seconds."""
    since = now() - window
    count = db.execute(
        "SELECT COUNT(*) FROM rate_events WHERE scope = ? AND created > ?", (scope, since)
    ).fetchone()[0]
    return count >= limit


def record(db, scope):
    """Note that something happened. Events older than a day are deleted as housekeeping."""
    db.execute("DELETE FROM rate_events WHERE created < ?", (now() - 86400,))
    db.execute("INSERT INTO rate_events (scope, created) VALUES (?, ?)", (scope, now()))
    db.commit()


def clear(db, scope):
    db.execute("DELETE FROM rate_events WHERE scope = ?", (scope,))
    db.commit()