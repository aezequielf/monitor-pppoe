"""LeaseManager: recurso exclusivo = 1 conexión SSH + 1 poller por slot.

Caso A del diseño: cada viewer ocupa un slot y monitorea su propio subscriber.
La cantidad de slots se controla con `MAX_SESIONES`.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import anyio

from ..bras.client import BrasClient
from ..bras.parser import parse_access_user, to_snapshot
from ..config import Settings
from ..schemas import MonitorSnapshot


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LeaseBusy(Exception):
    """No hay slots libres."""

    def __init__(self, lease: "Lease") -> None:
        self.lease = lease
        super().__init__("Recurso ocupado")


@dataclass
class Lease:
    id: str
    token: str
    owner: str
    username: str
    created_at: datetime
    expires_at: datetime
    last_heartbeat: datetime
    state: str = "connecting"
    client: Any = None
    snapshot: MonitorSnapshot | None = None
    version: int = 0
    poller: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    active_streams: int = 0
    disconnected_at: float | None = None
    release_reason: str | None = None

    def seconds_left(self) -> int:
        return max(0, int((self.expires_at - _now()).total_seconds()))


ClientFactory = Callable[[Settings], Any]


class LeaseManager:
    def __init__(
        self, settings: Settings, client_factory: ClientFactory | None = None
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or BrasClient
        self._leases: dict[str, Lease] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    # --- ciclo de vida ---------------------------------------------------

    def start(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reaper_loop())

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for lease in list(self._leases.values()):
            await self.release(lease, reason="shutdown")

    # --- consultas -------------------------------------------------------

    def get(self, lease_id: str) -> Lease | None:
        return self._leases.get(lease_id)

    def find_by_token(self, token: str) -> Lease | None:
        if not token:
            return None
        for lease in self._leases.values():
            if secrets.compare_digest(lease.token, token):
                return lease
        return None

    def list_leases(self) -> list[Lease]:
        return list(self._leases.values())

    def occupied(self) -> int:
        return len(self._leases)

    def free(self) -> int:
        return max(0, self._settings.max_sesiones - len(self._leases))

    # --- acquire / release ----------------------------------------------

    async def acquire(self, owner: str, username: str) -> Lease:
        async with self._lock:
            if len(self._leases) >= self._settings.max_sesiones:
                raise LeaseBusy(next(iter(self._leases.values())))
            now = _now()
            lease = Lease(
                id=uuid.uuid4().hex,
                token=secrets.token_urlsafe(32),
                owner=owner,
                username=username,
                created_at=now,
                expires_at=now + timedelta(seconds=self._settings.session_ttl),
                last_heartbeat=now,
            )
            self._leases[lease.id] = lease

        client = self._client_factory(self._settings)
        try:
            client.validate_username(username)
            await anyio.to_thread.run_sync(client.connect)
        except Exception:
            async with self._lock:
                self._leases.pop(lease.id, None)
            raise

        lease.client = client
        lease.state = "active"
        # Import local para evitar ciclo en tiempo de import.
        from .poller import run_poller

        lease.poller = asyncio.create_task(run_poller(self, lease))
        return lease

    async def release(self, lease: Lease, reason: str = "manual") -> None:
        async with self._lock:
            if self._leases.get(lease.id) is not lease:
                return
            del self._leases[lease.id]

        lease.state = "releasing"
        lease.release_reason = reason
        self._push(lease, {"event": "released", "reason": reason})
        lease.released.set()

        poller = lease.poller
        if poller is not None and not poller.done():
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await poller

        if lease.client is not None:
            await anyio.to_thread.run_sync(lease.client.close)
            lease.client = None

        lease.state = "released"

    def heartbeat(self, lease: Lease) -> None:
        lease.last_heartbeat = _now()

    # --- publicación -----------------------------------------------------

    def publish_snapshot(self, lease: Lease, result) -> MonitorSnapshot:
        lease.version += 1
        snapshot = to_snapshot(lease.username, result, version=lease.version)
        lease.snapshot = snapshot
        self._push(lease, {"event": "snapshot", "snapshot": snapshot})
        return snapshot

    def publish_error(self, lease: Lease, message: str) -> MonitorSnapshot:
        lease.version += 1
        snapshot = MonitorSnapshot(
            username=lease.username,
            online=True,
            state="error",
            error_msg=message,
            version=lease.version,
            collected_at=_now(),
        )
        lease.snapshot = snapshot
        self._push(lease, {"event": "snapshot", "snapshot": snapshot})
        return snapshot

    def _push(self, lease: Lease, message: dict) -> None:
        for queue in list(lease.subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(message)

    # --- reaper ----------------------------------------------------------

    async def _reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                await self._reap_once()
        except asyncio.CancelledError:
            return

    async def _reap_once(self) -> None:
        now_dt = _now()
        now_mono = time.monotonic()
        for lease in list(self._leases.values()):
            if now_dt >= lease.expires_at:
                await self.release(lease, reason="expired")
                continue
            if (
                self._settings.heartbeat_ttl > 0
                and (now_dt - lease.last_heartbeat).total_seconds()
                > self._settings.heartbeat_ttl
            ):
                await self.release(lease, reason="heartbeat")
                continue
            if (
                lease.active_streams == 0
                and lease.disconnected_at is not None
                and now_mono - lease.disconnected_at
                >= self._settings.disconnect_grace
            ):
                await self.release(lease, reason="disconnected")
                continue
