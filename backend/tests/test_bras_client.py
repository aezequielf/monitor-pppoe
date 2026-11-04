from __future__ import annotations

from app.bras.client import BrasClient
from app.config import Settings


class FakeConnection:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.commands: list[str] = []

    def send_command(self, command: str, **kwargs) -> str:
        self.commands.append(command)
        return ""

    def enable(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True


def test_connect_uses_supported_netmiko_timeout_kwarg(monkeypatch) -> None:
    captured: dict = {}

    def fake_handler(**kwargs) -> FakeConnection:
        captured.update(kwargs)
        return FakeConnection(**kwargs)

    monkeypatch.setattr("app.bras.client.ConnectHandler", fake_handler)

    settings = Settings(
        bras_host="198.51.100.1",
        bras_user="monitor",
        bras_password="secret",
        bras_conn_timeout=7,
        bras_read_timeout=42,
    )
    client = BrasClient(settings).connect()

    assert "read_timeout" not in captured
    assert captured["read_timeout_override"] == 42
    assert captured["conn_timeout"] == 7
    assert client.query("usuario") == ""
