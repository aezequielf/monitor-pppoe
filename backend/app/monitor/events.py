"""Generador SSE y detección de desconexión del cliente."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import AsyncIterator

from ..schemas import MonitorSnapshot
from .lease import Lease

KEEPALIVE_SECONDS = 15.0


def _snapshot_frame(snapshot: MonitorSnapshot) -> str:
    return f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n"


def _released_frame(reason: str | None) -> str:
    if reason == "expired":
        event = "expired"
    elif reason == "ssh_error":
        event = "error"
    else:
        event = "closed"
    data = json.dumps({"reason": reason})
    return f"event: {event}\ndata: {data}\n\n"


def _ping_frame() -> str:
    return ": ping\n\n"


async def event_stream(lease: Lease) -> AsyncIterator[str]:
    """Emite snapshots hasta que el lease se libere o el cliente se desconecte.

    Al cerrarse el generador (pestaña cerrada, red cortada, cancelación del
    servidor) el bloque `finally` registra la desconexión para que el reaper
    libere el recurso tras la gracia configurada.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=4)
    lease.subscribers.add(queue)
    lease.active_streams += 1
    lease.disconnected_at = None

    try:
        if lease.snapshot is not None:
            yield _snapshot_frame(lease.snapshot)
        else:
            yield _ping_frame()

        while True:
            if lease.released.is_set() and queue.empty():
                yield _released_frame(lease.release_reason)
                return
            try:
                message = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_SECONDS
                )
            except asyncio.TimeoutError:
                yield _ping_frame()
                continue

            if message.get("event") == "snapshot":
                yield _snapshot_frame(message["snapshot"])
            elif message.get("event") == "released":
                yield _released_frame(message.get("reason"))
                return
    except asyncio.CancelledError:
        raise
    finally:
        lease.subscribers.discard(queue)
        lease.active_streams = max(0, lease.active_streams - 1)
        if lease.active_streams == 0:
            lease.disconnected_at = time.monotonic()


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
