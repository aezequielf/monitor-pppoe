"""Loop de consulta periódica del BRAS para un lease."""

from __future__ import annotations

import asyncio

import anyio

from ..bras.parser import parse_access_user
from ..schemas import ParseResult
from .lease import Lease, LeaseManager


def _has_changed(previous, result: ParseResult) -> bool:
    if previous is None:
        return True
    if previous.state != result.state:
        return True
    if previous.static != result.static:
        return True
    if previous.latest is None or result.latest is None:
        return previous.latest is not result.latest
    return (
        previous.latest.in_raw != result.latest.in_raw
        or previous.latest.out_raw != result.latest.out_raw
    )


async def run_poller(manager: LeaseManager, lease: Lease) -> None:
    settings = manager.settings
    client = lease.client

    try:
        while not lease.stop_event.is_set():
            try:
                raw = await anyio.to_thread.run_sync(client.query, lease.username)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                manager.publish_error(lease, f"Error de SSH: {exc}")
                # No esperamos aquí: `release` cancelaría esta misma tarea.
                asyncio.create_task(manager.release(lease, reason="ssh_error"))
                return

            result = parse_access_user(
                raw,
                up_field=settings.dir_up,
                down_field=settings.dir_down,
                unit_bytes=settings.kbyte_unit_bytes,
                time_base=settings.kbyte_time_base,
            )
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
