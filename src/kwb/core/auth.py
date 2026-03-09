"""
Simple user authentication for Debussy.

JSON-file-based user store with bcrypt-like hashing (using hashlib as fallback).
Session tokens with configurable expiry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path


_TOKEN_EXPIRY = int(os.environ.get("KWB_SESSION_EXPIRY", 86400))  # 24h default


def _hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """Hash a password with a random salt. Returns (hash, salt)."""
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return h.hex(), salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


@dataclass
class User:
    username: str
    password_hash: str = ""
    salt: str = ""
    display_name: str = ""
    role: str = "user"    # "admin" | "user"
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "password_hash": self.password_hash,
            "salt": self.salt,
            "display_name": self.display_name,
            "role": self.role,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "User":
        return User(
            username=d["username"],
            password_hash=d.get("password_hash", ""),
            salt=d.get("salt", ""),
            display_name=d.get("display_name", ""),
            role=d.get("role", "user"),
            created_at=d.get("created_at", 0.0),
        )


@dataclass
class Session:
    token: str
    username: str
    created_at: float = 0.0
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class UserStore:
    """JSON-file-backed user store."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else None
        self._users: dict[str, User] = {}
        self._sessions: dict[str, Session] = {}
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for u in data.get("users", []):
                user = User.from_dict(u)
                self._users[user.username] = user
        except Exception:
            pass

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"users": [u.to_dict() for u in self._users.values()]}
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    def create_user(
        self, username: str, password: str,
        display_name: str = "", role: str = "user",
    ) -> User:
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        pw_hash, salt = _hash_password(password)
        user = User(
            username=username,
            password_hash=pw_hash,
            salt=salt,
            display_name=display_name or username,
            role=role,
            created_at=time.time(),
        )
        self._users[username] = user
        self._save()
        return user

    def authenticate(self, username: str, password: str) -> Session | None:
        """Verify credentials and create a session. Returns None on failure."""
        user = self._users.get(username)
        if not user:
            return None
        if not _verify_password(password, user.password_hash, user.salt):
            return None
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(
            token=token, username=username,
            created_at=now, expires_at=now + _TOKEN_EXPIRY,
        )
        self._sessions[token] = session
        self._cleanup_sessions()
        return session

    def validate_session(self, token: str) -> User | None:
        """Validate a session token. Returns the User or None."""
        session = self._sessions.get(token)
        if not session or session.is_expired:
            if session:
                del self._sessions[token]
            return None
        return self._users.get(session.username)

    def logout(self, token: str) -> bool:
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False

    def list_users(self) -> list[dict]:
        return [
            {"username": u.username, "display_name": u.display_name, "role": u.role}
            for u in self._users.values()
        ]

    def user_count(self) -> int:
        return len(self._users)

    def get_user(self, username: str) -> User | None:
        return self._users.get(username)

    def _cleanup_sessions(self) -> None:
        expired = [k for k, s in self._sessions.items() if s.is_expired]
        for k in expired:
            del self._sessions[k]

    def ensure_default_admin(self) -> bool:
        """Create a default admin if no users exist. Returns True if created."""
        if self._users:
            return False
        default_pw = os.environ.get("KWB_ADMIN_PASSWORD", "debussy")
        self.create_user("admin", default_pw, display_name="Administrator", role="admin")
        return True
