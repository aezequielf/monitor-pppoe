"""Endpoints de autenticación."""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..config import get_settings
from ..schemas import LoginRequest, TokenResponse, UserInfo
from .dependencies import get_current_user
from .jwt import (
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from .users import authenticate

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response) -> TokenResponse:
    """Valida las credenciales y devuelve un access token.

    También setea la cookie httpOnly del refresh token (mismo origen).
    """
    if not authenticate(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    settings = get_settings()
    _set_refresh_cookie(response, create_refresh_token(body.username))
    return TokenResponse(
        access_token=create_access_token(body.username),
        expires_in=settings.access_ttl,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response) -> TokenResponse:
    """Emite un access token nuevo a partir de la cookie de refresh."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No hay refresh token",
        )
    try:
        payload = decode_token(token, REFRESH)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o vencido",
        ) from exc
    settings = get_settings()
    _set_refresh_cookie(response, create_refresh_token(payload["sub"]))
    return TokenResponse(
        access_token=create_access_token(payload["sub"]),
        expires_in=settings.access_ttl,
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    """Borra la cookie de refresh del navegador."""
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return {"status": "ok"}


@router.get("/me", response_model=UserInfo)
def me(username: str = Depends(get_current_user)) -> UserInfo:
    """Devuelve el operador autenticado por el access token."""
    return UserInfo(username=username)
