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
