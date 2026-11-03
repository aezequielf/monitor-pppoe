"""Endpoints de monitoreo: acquire, stream (SSE), heartbeat, release, status."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_user
from ..schemas import MonitorSnapshot
from .events import SSE_HEADERS, event_stream
from .lease import Lease, LeaseBusy, LeaseManager

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])

LEASE_TOKEN_HEADER = "X-Lease-Token"


class AcquireRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class AcquireResponse(BaseModel):
    lease_id: str
    lease_token: str
    username: str
    expires_at: datetime
    expires_in: int


def get_manager(request: Request) -> LeaseManager:
    manager = getattr(request.app.state, "lease_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Servicio no inicializado")
    return manager


def _authorize(manager: LeaseManager, token: Optional[str], owner: str) -> Lease:
    if not token:
        raise HTTPException(status_code=401, detail="Falta el header X-Lease-Token")
    lease = manager.find_by_token(token)
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease no encontrado o expirado")
    if lease.owner != owner:
        raise HTTPException(status_code=403, detail="El lease pertenece a otro usuario")
    return lease


@router.post(
    "/leases",
    response_model=AcquireResponse,
    status_code=201,
    responses={
        409: {"description": "El recurso exclusivo está ocupado por otro operador."},
        502: {"description": "No se pudo conectar o consultar el BRAS."},
    },
)
async def acquire(
    body: AcquireRequest,
    owner: str = Depends(get_current_user),
    manager: LeaseManager = Depends(get_manager),
) -> AcquireResponse:
    """Toma el recurso exclusivo y comienza a consultar al BRAS.

    Devuelve el `lease_token` (usar en `X-Lease-Token`) y el vencimiento duro.
    Si no hay cupo responde `409` con el dueño actual y los segundos restantes.
    """
    try:
        lease = await manager.acquire(owner, body.username)
    except LeaseBusy as exc:
        busy = exc.lease
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Recurso ocupado",
                "owner": busy.owner,
                "expira_en": busy.expires_at.isoformat(),
                "segundos_restantes": busy.seconds_left(),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - se reporta como fallo del BRAS
        raise HTTPException(
            status_code=502, detail=f"No se pudo conectar al BRAS: {exc}"
        ) from exc

    return AcquireResponse(
        lease_id=lease.id,
        lease_token=lease.token,
        username=lease.username,
        expires_at=lease.expires_at,
        expires_in=lease.seconds_left(),
    )


@router.get("/stream")
async def stream(
    lease_token: str = Query(..., min_length=1),
    manager: LeaseManager = Depends(get_manager),
) -> StreamingResponse:
    """Stream SSE con los snapshots del abonado monitoreado.

    EventSource no permite headers custom: el `lease_token` va por query
    (es un token efímero, atado al lease).
    """
    lease = manager.find_by_token(lease_token)
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease no encontrado o expirado")
    return StreamingResponse(
        event_stream(lease),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/heartbeat", status_code=204)
def heartbeat(
    lease_token: Optional[str] = Header(default=None, alias=LEASE_TOKEN_HEADER),
    owner: str = Depends(get_current_user),
    manager: LeaseManager = Depends(get_manager),
) -> Response:
    """Renueva el lease; si el navegador deja de enviarlo, el reaper lo libera."""
    lease = _authorize(manager, lease_token, owner)
    manager.heartbeat(lease)
    return Response(status_code=204)


@router.delete("/leases", status_code=204)
async def release(
    lease_token: Optional[str] = Header(default=None, alias=LEASE_TOKEN_HEADER),
    owner: str = Depends(get_current_user),
    manager: LeaseManager = Depends(get_manager),
) -> Response:
    """Libera el recurso y cierra la conexión SSH del slot."""
    lease = _authorize(manager, lease_token, owner)
    await manager.release(lease, reason="manual")
    return Response(status_code=204)


@router.get("/snapshot", response_model=MonitorSnapshot)
def snapshot(
    lease_token: Optional[str] = Header(default=None, alias=LEASE_TOKEN_HEADER),
    owner: str = Depends(get_current_user),
    manager: LeaseManager = Depends(get_manager),
) -> MonitorSnapshot:
    """Último snapshot disponible (alternativa a SSE para clientes/API)."""
    lease = _authorize(manager, lease_token, owner)
    if lease.snapshot is None:
        raise HTTPException(status_code=404, detail="Todavía no hay datos")
    return lease.snapshot


@router.get("/status")
def status_info(
    owner: str = Depends(get_current_user),
    manager: LeaseManager = Depends(get_manager),
) -> dict:
    """Capacidad, ocupación y leases activos (sin exponer sus tokens)."""
    return {
        "capacidad": manager.settings.max_sesiones,
        "ocupados": manager.occupied(),
        "libres": manager.free(),
        "leases": [
            {
                "id": lease.id,
                "owner": lease.owner,
                "estado": lease.state,
                "expira_en": lease.expires_at.isoformat(),
                "segundos_restantes": lease.seconds_left(),
            }
            for lease in manager.list_leases()
        ],
    }
