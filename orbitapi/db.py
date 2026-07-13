"""Tiny SQLite layer. Rows come back as plain dicts."""
import os
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional

from . import config

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
    return _conn


def query(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    with _lock:
        cur = conn().execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with _lock:
        cur = conn().execute(sql, tuple(params))
        return cur.lastrowid


def raw(sql: str) -> List[Dict[str, Any]]:
    """Run a raw SQL string (used by endpoints that build SQL by hand)."""
    with _lock:
        cur = conn().execute(sql)
        return [dict(r) for r in cur.fetchall()]


def script(sql: str) -> None:
    with _lock:
        conn().executescript(sql)


def reset_connection() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
