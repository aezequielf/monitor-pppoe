from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config as config_module
from app.auth import users
from app.auth.dependencies import get_current_user
from app.auth.router import router as auth_router
from app.monitor.lease import LeaseBusy
from app.monitor.router import get_manager
from app.monitor.router import router as monitor_router
from app.schemas import LatestSample, MonitorSnapshot, StaticInfo


class FakeLease:
    def __init__(self, owner: str = "alice", username: str = "usuario") -> None:
        self.id = "lease-1"
        self.token = "lease-token-1"
        self.owner = owner
        self.username = username
        self.state = "active"
        self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.snapshot = MonitorSnapshot(
            username=username,
            online=True,
            state="ok",
            collected_at=datetime.now(timezone.utc),
            static=StaticInfo(
                mac="00:11:22:33:44:55",
                ip="203.0.113.10",
                start_time="2026-11-03 10:00:00",
                in_qos="PLAN-100",
                out_qos="PLAN-100",
                in_pir_kbps=100000,
                out_cir_kbps=100000,
            ),
            latest=LatestSample(
                ts=datetime.now(timezone.utc),
                up_mbps=12.5,
                down_mbps=88.25,
                up_bytes=8_941_651_101,
                down_bytes=43_149_452_521,
            ),
        )

    def seconds_left(self) -> int:
        return 300


class FakeManager:
    def __init__(self) -> None:
        self.lease = FakeLease()
        self.settings = SimpleNamespace(max_sesiones=1)
        self.busy = False
        self.released: list[str | None] = []
        self.heartbeats = 0

    async def acquire(self, owner: str, username: str) -> FakeLease:
        if self.busy:
            raise LeaseBusy(self.lease)
        self.lease = FakeLease(owner=owner, username=username)
        return self.lease

    def find_by_token(self, token: str) -> FakeLease | None:
        return self.lease if token == self.lease.token else None

    def heartbeat(self, lease: FakeLease) -> None:
        self.heartbeats += 1

    async def release(self, lease: FakeLease, reason: str | None = None) -> None:
        self.released.append(reason)

    def occupied(self) -> int:
        return 1

    def free(self) -> int:
        return 0

    def list_leases(self) -> list[FakeLease]:
        return [self.lease]


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv(
        "JWT_SECRET", "test-secret-value-012345678901234567890123456789"
    )
    config_module.get_settings.cache_clear()
    users.init_db()
    users.create_user("alice", "secret-password")

    app = FastAPI()
    app.include_router(auth_router)
    with TestClient(app) as client:
        yield client
    config_module.get_settings.cache_clear()


@pytest.fixture
def monitor_client():
    app = FastAPI()
    app.include_router(monitor_router)
    manager = FakeManager()
    app.dependency_overrides[get_manager] = lambda: manager
    app.dependency_overrides[get_current_user] = lambda: "alice"
    with TestClient(app) as client:
        yield client, manager


# --- Auth ---------------------------------------------------------------


def test_login_rejects_bad_credentials(auth_client) -> None:
    response = auth_client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_refresh_me_and_logout(auth_client) -> None:
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "secret-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert auth_client.cookies.get("refresh_token")

    me = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json() == {"username": "alice"}

    refreshed = auth_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    assert auth_client.post("/api/v1/auth/logout").status_code == 200
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_me_requires_token(auth_client) -> None:
    assert auth_client.get("/api/v1/auth/me").status_code == 401


# --- Monitor ------------------------------------------------------------


def test_acquire_returns_lease(monitor_client) -> None:
    client, manager = monitor_client
    response = client.post(
        "/api/v1/monitor/leases", json={"username": "usuario"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "usuario"
    assert body["lease_id"] == "lease-1"
    assert body["lease_token"] == "lease-token-1"
    assert body["expires_in"] == 300


def test_acquire_validation_error(monitor_client) -> None:
    client, _ = monitor_client
    response = client.post("/api/v1/monitor/leases", json={"username": ""})
    assert response.status_code == 422


def test_acquire_busy_returns_owner_and_eta(monitor_client) -> None:
    client, manager = monitor_client
    manager.busy = True
    response = client.post(
        "/api/v1/monitor/leases", json={"username": "usuario"}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["owner"] == "alice"
    assert detail["segundos_restantes"] == 300
    assert "expira_en" in detail


def test_heartbeat_and_release(monitor_client) -> None:
    client, manager = monitor_client

    missing = client.post("/api/v1/monitor/heartbeat")
    assert missing.status_code == 401

    unknown = client.post(
        "/api/v1/monitor/heartbeat", headers={"X-Lease-Token": "nope"}
    )
    assert unknown.status_code == 404

    ok = client.post(
        "/api/v1/monitor/heartbeat",
        headers={"X-Lease-Token": manager.lease.token},
    )
    assert ok.status_code == 204
    assert manager.heartbeats == 1

    released = client.delete(
        "/api/v1/monitor/leases", headers={"X-Lease-Token": manager.lease.token}
    )
    assert released.status_code == 204
    assert manager.released == ["manual"]


def test_snapshot_returns_typed_payload(monitor_client) -> None:
    client, manager = monitor_client
    response = client.get(
        "/api/v1/monitor/snapshot",
        headers={"X-Lease-Token": manager.lease.token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ok"
    assert body["static"]["ip"] == "203.0.113.10"
    assert body["static"]["start_time"] == "2026-11-03 10:00:00"
    assert body["latest"]["up_mbps"] == 12.5
    assert body["latest"]["down_mbps"] == 88.25
    assert body["latest"]["up_bytes"] == 8_941_651_101
    assert body["latest"]["down_bytes"] == 43_149_452_521


def test_snapshot_requires_matching_lease_owner(monitor_client) -> None:
    client, manager = monitor_client
    manager.lease.owner = "bob"
    response = client.get(
        "/api/v1/monitor/snapshot",
        headers={"X-Lease-Token": manager.lease.token},
    )
    assert response.status_code == 403


def test_status_lists_leases(monitor_client) -> None:
    client, _ = monitor_client
    response = client.get("/api/v1/monitor/status")
    assert response.status_code == 200
    body = response.json()
    assert body["capacidad"] == 1
    assert body["ocupados"] == 1
    assert body["leases"][0]["owner"] == "alice"


def test_stream_unknown_lease_returns_404(monitor_client) -> None:
    client, _ = monitor_client
    response = client.get("/api/v1/monitor/stream", params={"lease_token": "nope"})
    assert response.status_code == 404
