"""Consulta del historial de conexiones en el webservice Radius."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

import httpx

from .config import Settings
from .schemas import HistoryConnection


class ConnectionHistoryError(Exception):
    """Error controlado al consultar el historial de conexiones."""


def _duration_seconds(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    seconds = int((end_dt - start_dt).total_seconds())
    return seconds if seconds >= 0 else None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = _text(value)
    if text is None or not text.isdigit():
        return None
    return int(text)


def _history_url(settings: Settings) -> str:
    base = settings.online_users_url.rstrip("/")
    return base if base.endswith(".php") else f"{base}/index.php"


def parse_connection_history(
    payload: Any, limit: int = 5
) -> list[HistoryConnection]:
    """Convierte la respuesta de `consulta-con` en los últimos `limit` registros."""
    if not isinstance(payload, dict):
        raise ConnectionHistoryError(
            "El servicio de historial devolvió un formato inesperado"
        )

    status = payload.get("status")
    result = payload.get("resultado")
    if status != "ok":
        detail = result if isinstance(result, str) else "respuesta inválida"
        raise ConnectionHistoryError(f"El servicio de historial respondió: {detail}")
    if isinstance(result, str):
        return []
    if not isinstance(result, list):
        raise ConnectionHistoryError(
            "El servicio de historial devolvió un formato inesperado"
        )

    records: list[HistoryConnection] = []
    for item in result[: max(0, limit)]:
        if not isinstance(item, dict):
            continue
        start = _text(item.get("inicio"))
        end = _text(item.get("final"))
        records.append(
            HistoryConnection(
                start=start,
                end=end,
                duration_seconds=_duration_seconds(start, end),
                upload_bytes=_int(item.get("upload")),
                download_bytes=_int(item.get("download")),
                nas=_text(item.get("nas")),
                reason=_text(item.get("causa")),
                mac=_text(item.get("mac")),
                ip=_text(item.get("ip")),
            )
        )
    return records


async def fetch_connection_history(
    username: str, settings: Settings, limit: int = 5
) -> list[HistoryConnection]:
    """Consulta server-side las últimas conexiones de un abonado."""
    if not re.fullmatch(settings.username_regex, username):
        raise ConnectionHistoryError("Nombre de usuario inválido")

    params = {"accion": "consulta-con", "login": username}
    try:
        async with httpx.AsyncClient(
            timeout=settings.online_users_timeout, trust_env=False
        ) as client:
            response = await client.get(_history_url(settings), params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ConnectionHistoryError(
            f"No se pudo consultar el historial: {exc}"
        ) from exc

    return parse_connection_history(payload, limit=limit)
