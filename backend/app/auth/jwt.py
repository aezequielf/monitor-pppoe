"""Emisión y validación de tokens JWT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..config import get_settings

ACCESS = "access"
REFRESH = "refresh"


def _encode(subject: str, token_type: str, ttl: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_access_token(username: str) -> str:
    return _encode(username, ACCESS, get_settings().access_ttl)


def create_refresh_token(username: str) -> str:
    return _encode(username, REFRESH, get_settings().refresh_ttl)


def decode_token(token: str, expected_type: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Tipo de token inválido")
    if not payload.get("sub"):
        raise jwt.InvalidTokenError("Token sin sujeto")
    return payload
