from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import online_users as online_users_module
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.online_users import router as online_users_router


class FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def fake_client_factory(payload, captured: dict, error: Exception | None = None):
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def get(self, url: str, params: dict | None = None) -> FakeResponse:
            captured["url"] = url
            captured["params"] = params
            if error is not None:
                raise error
            return FakeResponse(payload)

    return FakeClient


@pytest.fixture
def online_client(monkeypatch):
    app = FastAPI()
    app.include_router(online_users_router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    app.dependency_overrides[get_settings] = lambda: Settings(
        online_users_url="http://nas.test/webserv/",
        online_users_nas_ip="200.49.120.10",
        online_users_timeout=1.5,
    )

    captured: dict = {}

    def respond(payload=None, error: Exception | None = None) -> None:
        monkeypatch.setattr(
            online_users_module.httpx,
            "AsyncClient",
            fake_client_factory(payload, captured, error),
        )

    with TestClient(app) as client:
        yield client, app, captured, respond


def test_online_users_queries_nas_and_dedupes(online_client) -> None:
    client, _, captured, respond = online_client
    respond(
        {
            "status": "ok",
            "resultado": ["gbaigosar", "gbarrera", "gbaigosar", "otro", "GBAPlus"],
        }
    )

    response = client.get("/api/v1/online-users", params={"prefix": "gba"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "resultado": ["gbaigosar", "gbarrera", "GBAPlus"],
    }
    assert captured["url"] == "http://nas.test/webserv/"
    assert captured["params"] == {
        "accion": "usuarios_online",
        "username": "gba",
        "ip": "200.49.120.10",
    }
    assert captured["client_kwargs"] == {"timeout": 1.5, "trust_env": False}


def test_online_users_returns_empty_list(online_client) -> None:
    client, _, _, respond = online_client
    respond({"status": "ok", "resultado": []})

    response = client.get("/api/v1/online-users", params={"prefix": "zzz"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "resultado": []}


def test_online_users_maps_upstream_error_to_502(online_client) -> None:
    client, _, _, respond = online_client
    respond({"status": "err", "resultado": "Accion no reconocida o faltante ----"})

    response = client.get("/api/v1/online-users", params={"prefix": "gba"})

    assert response.status_code == 502
    assert "Accion no reconocida" in response.json()["detail"]


def test_online_users_maps_connection_error_to_502(online_client) -> None:
    client, _, _, respond = online_client
    respond(error=httpx.ConnectError("sin ruta al NAS"))

    response = client.get("/api/v1/online-users", params={"prefix": "gba"})

    assert response.status_code == 502
    assert "No se pudo consultar" in response.json()["detail"]


def test_online_users_rejects_malformed_payload(online_client) -> None:
    client, _, _, respond = online_client
    respond({"status": "ok", "resultado": "no-es-lista"})

    response = client.get("/api/v1/online-users", params={"prefix": "gba"})

    assert response.status_code == 502


def test_online_users_requires_three_chars(online_client) -> None:
    client, _, captured, respond = online_client
    respond({"status": "ok", "resultado": []})

    response = client.get("/api/v1/online-users", params={"prefix": "gb"})

    assert response.status_code == 422
    assert captured == {}


def test_online_users_rejects_invalid_prefix(online_client) -> None:
    client, _, captured, respond = online_client
    respond({"status": "ok", "resultado": []})

    response = client.get("/api/v1/online-users", params={"prefix": "-abc"})

    assert response.status_code == 400
    assert captured == {}


def test_online_users_requires_auth(online_client) -> None:
    client, app, _, _ = online_client
    app.dependency_overrides.pop(get_current_user)

    response = client.get("/api/v1/online-users", params={"prefix": "gba"})

    assert response.status_code == 401
