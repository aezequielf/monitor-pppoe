from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.monitor.events import event_stream
from app.monitor.lease import LeaseBusy, LeaseManager

FIXTURE = Path(__file__).parent / "fixtures" / "salida.txt"


class FakeClient:
    def __init__(self, settings, raw) -> None:
        self._raw = raw
        self.connected = False
        self.closed = False
        self.queries = 0

    def validate_username(self, username: str) -> None:
        if not username or " " in username:
            raise ValueError("Nombre de usuario inválido")

    def connect(self) -> None:
        self.connected = True

    def query(self, username: str) -> str:
        self.queries += 1
        return self._raw

    def close(self) -> None:
        self.closed = True


def _factory(raw: str, made: list[FakeClient]):
    def make(settings: Settings) -> FakeClient:
        client = FakeClient(settings, raw)
        made.append(client)
        return client

    return make


def _settings(**overrides) -> Settings:
    base = {
        "poll_interval": 0.02,
        "session_ttl": 60,
        "disconnect_grace": 10,
        "heartbeat_ttl": 45,
        "max_sesiones": 1,
    }
    base.update(overrides)
    return Settings(**base)


async def _wait_snapshot(lease, attempts: int = 200) -> None:
    for _ in range(attempts):
        if lease.snapshot is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("No se generó snapshot")


def test_acquire_polls_and_release() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(_settings(), client_factory=_factory(raw, made))
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            assert lease.state == "active"
            await _wait_snapshot(lease)
            assert lease.snapshot is not None
            assert lease.snapshot.state == "ok"
            assert lease.snapshot.static is not None
            assert lease.snapshot.static.ip == "200.49.122.133"
            assert manager.occupied() == 1

            await manager.release(lease, reason="manual")
            assert manager.occupied() == 0
            assert made[0].closed is True
            assert lease.released.is_set()
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_busy_when_no_free_slots() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(_settings(), client_factory=_factory(raw, made))
        manager.start()
        try:
            first = await manager.acquire("alice", "usuario")
            with pytest.raises(LeaseBusy) as excinfo:
                await manager.acquire("bob", "otro")
            assert excinfo.value.lease.owner == "alice"
            await manager.release(first)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_sin_conexion_stops_poller_but_keeps_lease() -> None:
    raw = "Error: The user does not exist."
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(_settings(), client_factory=_factory(raw, made))
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            await _wait_snapshot(lease)
            assert lease.snapshot is not None
            assert lease.snapshot.state == "sin_conexion"
            await asyncio.sleep(0.05)
            assert lease.poller is not None and lease.poller.done()
            assert made[0].closed is True
            assert manager.occupied() == 1
            await manager.release(lease)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_multiple_sessions_publish_error() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(
            _settings(), client_factory=_factory(raw + "\n" + raw, made)
        )
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            await _wait_snapshot(lease)
            assert lease.snapshot is not None
            assert lease.snapshot.state == "error"
            await manager.release(lease)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_reaper_releases_expired() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(_settings(), client_factory=_factory(raw, made))
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            lease.expires_at = lease.expires_at - timedelta(days=1)
            await manager._reap_once()
            assert manager.occupied() == 0
            assert lease.release_reason == "expired"
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_event_stream_emits_snapshot_and_expired() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(_settings(), client_factory=_factory(raw, made))
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            stream = event_stream(lease)

            first = await asyncio.wait_for(anext(stream), timeout=1)
            assert first.startswith("event: snapshot") or first.startswith(": ping")

            await manager.release(lease, reason="expired")
            frames: list[str] = []
            async for frame in stream:
                frames.append(frame)
            await stream.aclose()
            assert any("event: expired" in frame for frame in frames)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_on_change_does_not_republish_same_values() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(
            _settings(poll_interval=0.01, sample_mode="on_change"),
            client_factory=_factory(raw, made),
        )
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            await _wait_snapshot(lease)
            version = lease.version
            await asyncio.sleep(0.1)
            assert lease.version == version
            await manager.release(lease)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())


def test_every_poll_republishes() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    made: list[FakeClient] = []

    async def scenario() -> None:
        manager = LeaseManager(
            _settings(poll_interval=0.01, sample_mode="every_poll"),
            client_factory=_factory(raw, made),
        )
        manager.start()
        try:
            lease = await manager.acquire("alice", "usuario")
            await _wait_snapshot(lease)
            await asyncio.sleep(0.1)
            assert lease.version > 1
            await manager.release(lease)
        finally:
            await manager.shutdown()

    asyncio.run(scenario())
