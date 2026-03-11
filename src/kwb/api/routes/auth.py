"""
Authentication routes: login, logout, user management.

Router prefix: /api/auth
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError("pip install fastapi")

from kwb.core.auth import UserStore
from kwb.api.deps import workspace_dir

router = APIRouter()

_user_store: UserStore | None = None


def _get_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore(workspace_dir() / "users.json")
        _user_store.ensure_default_admin()
    return _user_store


def get_current_user(request: Request) -> dict | None:
    """Extract and validate user from request. Returns user dict or None."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get("debussy_token", "")
    if not token:
        return None
    store = _get_store()
    user = store.validate_session(token)
    if not user:
        return None
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@router.post("/api/auth/login")
async def login(request: dict):
    """Authenticate with username/password. Returns session token."""
    username = (request.get("username") or "").strip()
    password = request.get("password", "")
    if not username or not password:
        return JSONResponse({"error": "Benutzername und Passwort erforderlich"}, 400)

    store = _get_store()
    session = store.authenticate(username, password)
    if not session:
        return JSONResponse({"error": "Ungültige Anmeldedaten"}, 401)

    user = store.get_user(username)
    resp = JSONResponse({
        "ok": True,
        "token": session.token,
        "username": username,
        "display_name": user.display_name if user else username,
        "role": user.role if user else "user",
        "expires_at": session.expires_at,
    })
    resp.set_cookie(
        "debussy_token", session.token,
        httponly=True, samesite="strict", max_age=86400,
    )
    return resp


@router.post("/api/auth/logout")
async def logout(request: Request):
    """Invalidate the current session."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("debussy_token", "")
    store = _get_store()
    store.logout(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("debussy_token")
    return resp


@router.get("/api/auth/me")
async def current_user(request: Request):
    """Return current user info based on session token."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Nicht angemeldet"}, 401)
    return user


@router.post("/api/auth/register")
async def register(request_body: dict, request: Request = None):
    """Register a new user (admin only, or if no users exist)."""
    store = _get_store()

    # If users exist, only admin can register new users
    if store.user_count() > 0 and request:
        caller = get_current_user(request)
        if not caller or caller.get("role") != "admin":
            return JSONResponse(
                {"error": "Nur Administratoren können neue Benutzer anlegen"}, 403,
            )

    username = (request_body.get("username") or "").strip()
    password = request_body.get("password", "")
    display_name = request_body.get("display_name", "")
    role = request_body.get("role", "user")

    if not username or not password:
        return JSONResponse({"error": "Benutzername und Passwort erforderlich"}, 400)
    if len(password) < 4:
        return JSONResponse({"error": "Passwort zu kurz (min. 4 Zeichen)"}, 400)

    try:
        user = store.create_user(username, password, display_name, role)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 409)

    return {
        "ok": True,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


@router.get("/api/auth/users")
async def list_users(request: Request):
    """List all users (admin only)."""
    caller = get_current_user(request)
    if not caller or caller.get("role") != "admin":
        return JSONResponse({"error": "Nur für Administratoren"}, 403)
    store = _get_store()
    return {"users": store.list_users()}
