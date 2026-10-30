"""Database access. The same code runs on SQLite (local development and the tests) and on
PostgreSQL (Vercel). If a DATABASE_URL is configured we talk to Postgres, otherwise to the
SQLite file. All the SQL in the app is written to work on both."""
import os
import sqlite3
import click
from flask import current_app, g

try:
    import psycopg
except ImportError:          # only needed when DATABASE_URL is set (Postgres)
    psycopg = None

# Use `except db.IntegrityError` (or `from db import IntegrityError`) for "duplicate" errors
IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())


def using_postgres():
    return bool(current_app.config.get("DATABASE_URL"))


class Row:
    """A result row readable by column name (row["id"]) or position (row[0]), like sqlite3.Row."""
    def __init__(self, values, names):
        self._values = values
        self._names = names

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._names.index(key)]
            except ValueError:
                raise KeyError(key) from None
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._names)


def _row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(tuple(values), names)


def to_pg(sql):
    """Turn SQLite-style SQL (? placeholders) into Postgres style (%s placeholders)."""
    return sql.replace("%", "%%").replace("?", "%s")


class PgConnection:
    """Wraps a psycopg connection so it behaves like the sqlite3 connection the app expects."""
    def __init__(self, url):
        # prepare_threshold=None keeps it compatible with pooled (pgbouncer) connection strings
        self.conn = psycopg.connect(url, row_factory=_row_factory, prepare_threshold=None)

    def execute(self, sql, params=()):
        return self.conn.execute(to_pg(sql), params)

    def executescript(self, script):
        return self.conn.execute(script)    # no parameters: Postgres accepts many statements

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    # g lives for one request, so we reuse one connection per request
    if "db" not in g:
        if using_postgres():
            g.db = PgConnection(current_app.config["DATABASE_URL"])
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row            # access columns by name
            g.db.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FKs unless enabled
    return g.db


def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    schema = "schema_pg.sql" if using_postgres() else "schema.sql"
    with current_app.open_resource(schema) as f:
        script = f.read().decode("utf8")
    conn = get_db()
    conn.executescript(script)
    conn.commit()


def run_migrations():
    """Apply every .sql file in the migrations folder that hasn't been applied yet, in
    file-name order, and remember which ones ran. Safe to run as often as you like.
    SQLite uses migrations/, Postgres uses migrations_pg/. Returns the files it applied."""
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}

    folder = os.path.join(current_app.root_path, "migrations_pg" if using_postgres() else "migrations")
    if not os.path.isdir(folder):
        return []
    duplicate = (psycopg.errors.DuplicateColumn,) if psycopg else ()
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
            except duplicate:
                conn.rollback()
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (filename,))
            conn.commit()
            applied.append(filename)
    return applied


@click.command("init-db")
def init_db_command():
    """Create the database tables (WIPES existing data: only for a brand-new database)."""
    if using_postgres() and not click.confirm(
            "This DELETES everything in the Postgres database. Continue?"):
        raise click.Abort()
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
