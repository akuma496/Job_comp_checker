import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _configure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row


def init_db() -> None:
    conn = sqlite3.connect(settings.db_full_path)
    try:
        _configure(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email) VALUES (1, ?)",
            (settings.user_email,),
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.db_full_path)
    _configure(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_or_create(conn: sqlite3.Connection, table: str, lookup: dict, defaults: dict | None = None) -> tuple[int, bool]:
    """Generic lookup-or-insert: find the row in `table` matching every key/value in
    `lookup`; if none exists, insert one with lookup + defaults merged in. Returns
    (id, created) — `created` is True when a new row was inserted, for callers that
    need to know (e.g. discovery.py tracking which boards are newly found).

    `table`/column names are always trusted, hardcoded literals from call sites in
    this codebase — never derived from user input — so the f-string interpolation
    of identifiers below (which can't be parameterized in SQL) is safe.
    """
    where_clause = " AND ".join(f"{col} = ?" for col in lookup)
    row = conn.execute(f"SELECT id FROM {table} WHERE {where_clause}", tuple(lookup.values())).fetchone()
    if row:
        return row["id"], False

    all_cols = {**lookup, **(defaults or {})}
    columns = ", ".join(all_cols.keys())
    placeholders = ", ".join("?" * len(all_cols))
    cursor = conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(all_cols.values()))
    return cursor.lastrowid, True
