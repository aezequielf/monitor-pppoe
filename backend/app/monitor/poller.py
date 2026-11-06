"""Loop de consulta periódica del BRAS para un lease."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import anyio

from ..bras.parser import parse_access_user
from ..schemas import HostMetrics, LatestSample, ParseResult
from .lease import Lease, LeaseManager
from .rates import RateTracker


def _has_changed(previous, result: ParseResult) -> bool:
    if previous is None:
        return True
    if previous.state != result.state:
        return True
    if previous.static != result.static:
        return True
    if (previous.host or HostMetrics()) != (result.host or HostMetrics()):
        return True
    if previous.latest is None or result.latest is None:
        return previous.latest is not result.latest
    return (
        previous.latest.up_mbps != result.latest.up_mbps
        or previous.latest.down_mbps != result.latest.down_mbps
    )


def _optional(call):
    try:
        return call()
    except Exception:
        return None


def _query_bundle(client, username: str) -> tuple[str, HostMetrics]:
    """Consulta el abonado y, sin cortar la sesión, las métricas del NAS."""
    raw = client.query(username)
    host = HostMetrics(
        cpu_percent=_optional(lambda: client.cpu_usage()),
        memory_percent=_optional(lambda: client.memory_usage()),
        online_users=_optional(lambda: client.online_users()),
    )
    return raw, host


def _query_qos(client, user_id: int) -> tuple[int | None, float, int | None, float]:
    """Consulta los contadores QoS y registra el instante de cada muestra."""
    up_bytes = _optional(lambda: client.qos_inbound(user_id))
    up_ts = time.monotonic()
    down_bytes = _optional(lambda: client.qos_outbound(user_id))
    down_ts = time.monotonic()
    return up_bytes, up_ts, down_bytes, down_ts


async def run_poller(manager: LeaseManager, lease: Lease) -> None:
    settings = manager.settings
    client = lease.client
    user_id: int | None = None
    rates = RateTracker()

    try:
        while not lease.stop_event.is_set():
            try:
                raw, host = await anyio.to_thread.run_sync(
                    _query_bundle, client, lease.username
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                manager.publish_error(lease, f"Error de SSH: {exc}")
                # No esperamos aquí: `release` cancelaría esta misma tarea.
                asyncio.create_task(manager.release(lease, reason="ssh_error"))
                return

            result = parse_access_user(raw)
            result.host = host
            if user_id is None:
                user_id = result.user_id

            if user_id is not None and result.state == "ok":
                up_bytes, up_ts, down_bytes, down_ts = await anyio.to_thread.run_sync(
                    _query_qos, client, user_id
                )
                start_time = result.static.start_time if result.static else None
                up_mbps, down_mbps = rates.update(
                    up_bytes=up_bytes,
                    up_ts=up_ts,
                    down_bytes=down_bytes,
                    down_ts=down_ts,
                    session_key=f"{user_id}:{start_time}",
                )
                if up_mbps is not None and down_mbps is not None:
                    result.latest = LatestSample(
                        ts=datetime.now(timezone.utc),
                        up_mbps=up_mbps,
                        down_mbps=down_mbps,
                        up_bytes=up_bytes,
                        down_bytes=down_bytes,
                    )
            else:
                rates.reset()

            if settings.sample_mode == "every_poll" or _has_changed(
                lease.snapshot, result
            ):
                manager.publish_snapshot(lease, result)

            if result.state == "sin_conexion":
                # Usuario inexistente / sin sesión: cortar poller y cerrar SSH,
                # pero mantener el lease hasta que venza o el operador lo cierre.
                await anyio.to_thread.run_sync(client.close)
                lease.client = None
                lease.state = "sin_conexion"
                return

            try:
                await asyncio.wait_for(
                    lease.stop_event.wait(), timeout=settings.poll_interval
                )
            except asyncio.TimeoutError:
                continue
            else:
                return
    except asyncio.CancelledError:
        raise
