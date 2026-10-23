"""Application data: registered lives, settings, the single account and sessions."""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from backend.collector import MonitorError, extract_video_id, validate_timezone

SESSION_TTL = 7 * 86400
MIN_PASSWORD = 10
DEFAULT_SETTINGS: dict[str, Any] = {"daily_quota": 10000, "live_interval": 15, "display_timezone": "Etc/GMT+3"}
LIMITS = {"daily_quota": (1, 1_000_000), "live_interval": (10, 300)}

_hasher = PasswordHasher()


def cipher_from_secret(secret: bytes) -> Fernet:
    """Turns any random secret into a 32-byte Fernet key."""
    if len(secret.strip()) < 32:
        raise MonitorError("The application secret must have at least 32 characters")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.strip()).digest()))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mask_key(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "…"


class Store:
    def __init__(self, path: str, cipher: Fernet):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.cipher = cipher
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS targets (
                video_id TEXT PRIMARY KEY, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL, share_enabled INTEGER NOT NULL DEFAULT 0, share_token TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1), password_hash TEXT NOT NULL,
                must_change INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, created_at REAL NOT NULL, expires_at REAL NOT NULL
            );
            """
        )

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------- lives
    def targets(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM targets ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def target(self, video_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM targets WHERE video_id=?", (video_id,)).fetchone()
        return dict(row) if row else None

    def add_target(self, url: str) -> dict[str, Any]:
        video_id = extract_video_id(url)
        if self.target(video_id):
            raise MonitorError(f"A live {video_id} já está cadastrada")
        self.db.execute(
            "INSERT INTO targets(video_id, url, created_at) VALUES(?, ?, ?)", (video_id, url.strip(), time.time())
        )
        self.db.commit()
        return self.target(video_id) or {}

    def update_target(self, video_id: str, *, enabled: bool | None = None, share_enabled: bool | None = None) -> dict:
        target = self.target(video_id)
        if not target:
            raise KeyError(video_id)
        if enabled is not None:
            self.db.execute("UPDATE targets SET enabled=? WHERE video_id=?", (int(enabled), video_id))
        if share_enabled is not None:
            token = target["share_token"] or secrets.token_urlsafe(18)
            self.db.execute(
                "UPDATE targets SET share_enabled=?, share_token=? WHERE video_id=?",
                (int(share_enabled), token, video_id),
            )
        self.db.commit()
        return self.target(video_id) or {}

    def rotate_share_token(self, video_id: str) -> dict[str, Any]:
        if not self.target(video_id):
            raise KeyError(video_id)
        self.db.execute("UPDATE targets SET share_token=? WHERE video_id=?", (secrets.token_urlsafe(18), video_id))
        self.db.commit()
        return self.target(video_id) or {}

    def delete_target(self, video_id: str) -> None:
        if self.db.execute("DELETE FROM targets WHERE video_id=?", (video_id,)).rowcount == 0:
            raise KeyError(video_id)
        self.db.commit()

    def shared_target(self, token: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM targets WHERE share_token=? AND share_enabled=1", (token,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------- settings
    def settings(self) -> dict[str, Any]:
        values = dict(DEFAULT_SETTINGS)
        for row in self.db.execute("SELECT key, value FROM settings WHERE key IN (?, ?, ?)", tuple(DEFAULT_SETTINGS)):
            default = DEFAULT_SETTINGS[row["key"]]
            values[row["key"]] = type(default)(row["value"])
        return values

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS or value is None:
                continue
            if key == "display_timezone":
                clean[key] = validate_timezone(str(value))
                continue
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise MonitorError(f"{key} deve ser um número inteiro") from exc
            low, high = LIMITS[key]
            if not low <= number <= high:
                raise MonitorError(f"{key} deve estar entre {low} e {high}")
            clean[key] = number
        for key, value in clean.items():
            self.db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        self.db.commit()
        return self.settings()

    def api_key(self) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
        if not row:
            return ""
        try:
            return self.cipher.decrypt(row["value"].encode()).decode()
        except InvalidToken:
            # The application secret changed: the old key can no longer be read.
            return ""

    def set_api_key(self, key: str) -> None:
        key = key.strip()
        if not key or len(key) > 200 or any(ch.isspace() for ch in key):
            raise MonitorError("Chave da API inválida")
        token = self.cipher.encrypt(key.encode()).decode()
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES('api_key', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (token,),
        )
        self.db.commit()

    def clear_api_key(self) -> None:
        self.db.execute("DELETE FROM settings WHERE key='api_key'")
        self.db.commit()

    # ------------------------------------------------------------- account and sessions
    def has_account(self) -> bool:
        return self.db.execute("SELECT 1 FROM account WHERE id=1").fetchone() is not None

    def must_change_password(self) -> bool:
        row = self.db.execute("SELECT must_change FROM account WHERE id=1").fetchone()
        return bool(row and row["must_change"])

    def set_password(self, password: str, *, must_change: bool) -> None:
        if len(password) < MIN_PASSWORD:
            raise MonitorError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres")
        self.db.execute(
            """INSERT INTO account(id, password_hash, must_change, updated_at) VALUES(1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET password_hash=excluded.password_hash,
                   must_change=excluded.must_change, updated_at=excluded.updated_at""",
            (_hasher.hash(password), int(must_change), time.time()),
        )
        self.db.execute("DELETE FROM sessions")
        self.db.commit()

    def reset_password(self) -> str:
        """Random password that must be changed on next sign-in; ends every session."""
        password = secrets.token_urlsafe(12)
        self.set_password(password, must_change=True)
        return password

    def verify_password(self, password: str) -> bool:
        row = self.db.execute("SELECT password_hash FROM account WHERE id=1").fetchone()
        if not row:
            return False
        try:
            _hasher.verify(row["password_hash"], password)
        except (VerificationError, InvalidHashError):
            return False
        if _hasher.check_needs_rehash(row["password_hash"]):
            self.db.execute("UPDATE account SET password_hash=? WHERE id=1", (_hasher.hash(password),))
            self.db.commit()
        return True

    def create_session(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(32)
        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self.db.execute(
            "INSERT INTO sessions(token_hash, created_at, expires_at) VALUES(?, ?, ?)",
            (_token_hash(token), now, now + SESSION_TTL),
        )
        self.db.commit()
        return token

    def valid_session(self, token: str | None, now: float | None = None) -> bool:
        if not token:
            return False
        now = time.time() if now is None else now
        row = self.db.execute("SELECT expires_at FROM sessions WHERE token_hash=?", (_token_hash(token),)).fetchone()
        return bool(row and row["expires_at"] > now)

    def delete_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
            self.db.commit()
