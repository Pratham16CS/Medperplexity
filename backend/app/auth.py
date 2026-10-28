"""Authentication and authorization services for hospital users."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr

from .db import get_db_connection, verify_password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserSummary(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    organization_code: str
    email: str
    full_name: str
    designation: str
    department: str
    role: str
    avatar_initials: str
    specialty: str
    secondary_specialties: list[str]
    theme: str


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        user = conn.execute(
            """SELECT u.*, o.name as org_name, o.code as org_code, o.tier as org_tier,
                      p.specialty, p.secondary_specialties_json, p.theme
               FROM users u
               JOIN organizations o ON u.organization_id = o.id
               LEFT JOIN user_preferences p ON u.id = p.user_id
               WHERE LOWER(u.email) = LOWER(?)""",
            (email.strip(),)
        ).fetchone()

        if not user:
            return None

        if user["status"] != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account is {user['status']}. Please contact your hospital administrator."
            )

        if not verify_password(password, user["password_hash"], user["salt"]):
            return None

        return dict(user)


def create_session(user_id: str, duration_hours: int = 48) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=duration_hours)

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO auth_sessions (token, user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (token, user_id, now.strftime("%Y-%m-%dT%H:%M:%SZ"), expires.strftime("%Y-%m-%dT%H:%M:%SZ"))
        )
    return token


def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db_connection() as conn:
        session = conn.execute(
            """SELECT s.user_id, s.expires_at,
                      u.id, u.organization_id, u.email, u.full_name, u.designation, u.department, u.role, u.status, u.avatar_initials,
                      o.name as org_name, o.code as org_code, o.tier as org_tier, o.entitlements_json,
                      p.specialty, p.secondary_specialties_json, p.preferred_date_range, p.theme
               FROM auth_sessions s
               JOIN users u ON s.user_id = u.id
               JOIN organizations o ON u.organization_id = o.id
               LEFT JOIN user_preferences p ON u.id = p.user_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, now_iso)
        ).fetchone()

        if not session:
            return None

        data = dict(session)
        data["secondary_specialties"] = json.loads(data.get("secondary_specialties_json") or "[]")
        data["entitlements"] = json.loads(data.get("entitlements_json") or "{}")
        return data


def delete_session(token: str) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to your hospital account.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_from_token(parts[1])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended or inactive."
        )

    return user


def require_role(*roles: str):
    def role_checker(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if user.get("role") not in roles and "platform_admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of the following roles: {', '.join(roles)}."
            )
        return user
    return role_checker

