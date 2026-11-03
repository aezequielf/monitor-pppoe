"""Almacén de usuarios (SQLite) con hash bcrypt."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import bcrypt

from ..config import get_settings

_BCRYPT_MAX_BYTES = 72


def _db_path() -> Path:
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def _hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError("La contraseña no puede superar 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_user(username: str, password: str) -> None:
    username = username.strip()
    if not username:
        raise ValueError("El usuario no puede estar vacío")
    password_hash = _hash_password(password)
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"El usuario '{username}' ya existe") from exc


def set_password(username: str, password: str) -> bool:
    password_hash = _hash_password(password)
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (password_hash, username),
        )
        return cursor.rowcount > 0


def authenticate(username: str, password: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return False
    return _verify_password(password, row["password_hash"])


def user_exists(username: str) -> bool:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row is not None


def list_users() -> list[str]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT username FROM users ORDER BY username").fetchall()
    return [row["username"] for row in rows]
