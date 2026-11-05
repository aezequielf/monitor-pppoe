"""Búsqueda de usuarios conectados al NAS para el autocompletado del panel.

El webservice de dialup es HTTP interno y no requiere autenticación. Se consulta
desde el backend (no desde el navegador) para evitar CORS y contenido mixto.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth.dependencies import get_current_user
from .config import Settings, get_settings

router = APIRouter(prefix="/api/v1", tags=["subscribers"])


class OnlineUsersResponse(BaseModel):
    status: str = "ok"
    resultado: list[str]


class OnlineUsersError(Exception):
    """Error controlado al consultar el webservice de usuarios."""


async def fetch_online_users(prefix: str, settings: Settings) -> list[str]:
    """Devuelve los usuarios online cuyo nombre empieza con `prefix`."""
    params = {
        "accion": "usuarios_online",
        "username": prefix,
        "ip": settings.online_users_nas_ip,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.online_users_timeout, trust_env=False
        ) as client:
            response = await client.get(settings.online_users_url, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OnlineUsersError(
            f"No se pudo consultar el servicio de usuarios: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise OnlineUsersError("El servicio de usuarios devolvió un formato inesperado")

    status = payload.get("status")
    result = payload.get("resultado")
    if status != "ok":
        detail = result if isinstance(result, str) else "respuesta inválida"
        raise OnlineUsersError(f"El servicio de usuarios respondió: {detail}")
    if not isinstance(result, list):
        raise OnlineUsersError("El servicio de usuarios devolvió un formato inesperado")

    seen: set[str] = set()
    users: list[str] = []
    for item in result:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        if not name.lower().startswith(prefix.lower()):
            continue
        seen.add(name)
        users.append(name)
    return users


@router.get(
    "/online-users",
    response_model=OnlineUsersResponse,
    responses={
        400: {"description": "Prefijo de usuario inválido."},
        502: {"description": "El servicio de usuarios no respondió o devolvió un error."},
    },
)
async def online_users(
    prefix: str = Query(..., min_length=3, max_length=64),
    _owner: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> OnlineUsersResponse:
    """Lista usuarios con sesión activa en el NAS que empiezan con `prefix`.

    Se usa para autocompletar el usuario del abonado. Requiere sesión de panel;
    el webservice externo se consulta server-side con el NAS configurado.
    """
    if not re.fullmatch(settings.username_regex, prefix):
        raise HTTPException(status_code=400, detail="Prefijo de usuario inválido")

    try:
        users = await fetch_online_users(prefix, settings)
    except OnlineUsersError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OnlineUsersResponse(status="ok", resultado=users)
