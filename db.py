import sqlite3
import click
from flask import current_app, g

def get_db():
    # g lives for one request, so we reuse one connection per request
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row            # access columns by name
        g.db.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FKs unless enabled
    return g.db

def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    with current_app.open_resource("schema.sql") as f:
        get_db().executescript(f.read().decode("utf8"))

@click.command("init-db")
def init_db_command():
    """Create the database tables."""
    init_db()
    click.echo("Database initialized.")

def init_app(app):
    app.teardown_appcontext(close_db)   # close connection after each request
    app.cli.add_command(init_db_command)