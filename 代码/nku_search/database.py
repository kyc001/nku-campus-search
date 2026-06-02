from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from .config import DB_PATH, ensure_dirs


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(
            """
            create table if not exists users (
                id integer primary key autoincrement,
                username text unique not null,
                email text,
                password_hash text not null,
                role text not null default '访客',
                interests text not null default '[]',
                created_at text not null
            );
            create table if not exists query_log (
                id integer primary key autoincrement,
                user_id integer,
                query text not null,
                ts text not null,
                result_count integer default 0
            );
            create table if not exists click_log (
                id integer primary key autoincrement,
                user_id integer,
                query text,
                url text not null,
                ts text not null
            );
            """
        )


def create_user(username: str, password: str, email: str = "", role: str = "访客", interests: list[str] | None = None) -> int:
    init_db()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into users(username, email, password_hash, role, interests, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                username.strip(),
                email.strip(),
                generate_password_hash(password),
                role,
                json.dumps(interests or [], ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        row = conn.execute("select * from users where username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user(user_id: int | None) -> dict[str, Any] | None:
    if not user_id:
        return None
    init_db()
    with connect() as conn:
        row = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def verify_user(username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(username)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def log_query(user_id: int | None, query: str, result_count: int) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "insert into query_log(user_id, query, ts, result_count) values (?, ?, ?, ?)",
            (user_id, query, datetime.now().isoformat(timespec="seconds"), result_count),
        )


def log_click(user_id: int | None, query: str, url: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "insert into click_log(user_id, query, url, ts) values (?, ?, ?, ?)",
            (user_id, query, url, datetime.now().isoformat(timespec="seconds")),
        )


def recent_queries(user_id: int | None, limit: int = 10) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                "select query, max(ts) as ts, max(result_count) as result_count from query_log where user_id = ? group by query order by ts desc limit ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "select query, max(ts) as ts, max(result_count) as result_count from query_log where user_id is null group by query order by ts desc limit ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def query_history(user_id: int | None, limit: int = 100, offset: int = 0, keyword: str = "") -> list[dict[str, Any]]:
    """Return per-event query log entries (not collapsed by query) for the history page."""
    init_db()
    like = f"%{keyword.strip()}%" if keyword and keyword.strip() else None
    with connect() as conn:
        if user_id:
            if like:
                rows = conn.execute(
                    "select query, ts, result_count from query_log where user_id = ? and query like ? order by ts desc limit ? offset ?",
                    (user_id, like, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select query, ts, result_count from query_log where user_id = ? order by ts desc limit ? offset ?",
                    (user_id, limit, offset),
                ).fetchall()
        else:
            if like:
                rows = conn.execute(
                    "select query, ts, result_count from query_log where user_id is null and query like ? order by ts desc limit ? offset ?",
                    (like, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select query, ts, result_count from query_log where user_id is null order by ts desc limit ? offset ?",
                    (limit, offset),
                ).fetchall()
    return [dict(row) for row in rows]


def query_history_count(user_id: int | None, keyword: str = "") -> int:
    init_db()
    like = f"%{keyword.strip()}%" if keyword and keyword.strip() else None
    with connect() as conn:
        if user_id:
            if like:
                row = conn.execute(
                    "select count(*) as n from query_log where user_id = ? and query like ?",
                    (user_id, like),
                ).fetchone()
            else:
                row = conn.execute("select count(*) as n from query_log where user_id = ?", (user_id,)).fetchone()
        else:
            if like:
                row = conn.execute(
                    "select count(*) as n from query_log where user_id is null and query like ?",
                    (like,),
                ).fetchone()
            else:
                row = conn.execute("select count(*) as n from query_log where user_id is null").fetchone()
    return int(row["n"]) if row else 0


def clear_history(user_id: int | None) -> None:
    init_db()
    with connect() as conn:
        if user_id:
            conn.execute("delete from query_log where user_id = ?", (user_id,))
        else:
            conn.execute("delete from query_log where user_id is null")


def user_profile(user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        return {"role": "访客", "interests": []}
    try:
        interests = json.loads(user.get("interests") or "[]")
    except json.JSONDecodeError:
        interests = []
    return {"role": user.get("role") or "访客", "interests": interests}


def clicked_urls(user_id: int | None, limit: int = 50) -> list[str]:
    if not user_id:
        return []
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "select url from click_log where user_id = ? order by ts desc limit ?",
            (user_id, limit),
        ).fetchall()
    return [row["url"] for row in rows]
