import os
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


def run_migrations():
    """Apply every .sql file in the migrations/ folder that hasn't been applied yet,
    in file-name order, and remember which ones ran. Safe to run as often as you like.
    Returns the list of files it applied."""
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}

    folder = os.path.join(current_app.root_path, "migrations")
    applied = []
    for filename in sorted(os.listdir(folder)):
        if filename.endswith(".sql") and filename not in done:
            with open(os.path.join(folder, filename), encoding="utf8") as f:
                script = f.read()
            try:
                conn.executescript(script)
            except sqlite3.OperationalError as error:
                # A database built from the newest schema.sql already has the column
                if "duplicate column name" not in str(error):
                    raise
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (filename,))
            conn.commit()
            applied.append(filename)
    return applied


@click.command("init-db")
def init_db_command():
    """Create the database tables (WIPES existing data: only for a brand-new database)."""
    init_db()
    click.echo("Database initialized.")


@click.command("migrate")
def migrate_command():
    """Update an existing database to the latest structure without deleting data."""
    applied = run_migrations()
    for name in applied:
        click.echo(f"Applied {name}")
    click.echo("Database is up to date.")


def init_app(app):
    app.teardown_appcontext(close_db)   # close connection after each request
    app.cli.add_command(init_db_command)
    app.cli.add_command(migrate_command)