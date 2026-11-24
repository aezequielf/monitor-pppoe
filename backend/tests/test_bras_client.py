from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.bras.client import BrasClient
from app.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
USER_XML = (FIXTURES / "access_user.xml").read_text(encoding="utf-8")
OFFLINE_XML = (FIXTURES / "offline_records.xml").read_text(encoding="utf-8")
QOS_XML = (FIXTURES / "qos_counters.xml").read_text(encoding="utf-8")


class FakeReply:
    ok = True
    error = ""

    def __init__(self, data_xml: str) -> None:
        self.data_xml = data_xml


class FakeManager:
    def __init__(self, data_xml: str) -> None:
        self.data_xml = data_xml
        self.filters: list[str] = []
        self.closed = False
        self.connected = True

    def get(self, filter):
        self.filters.append(filter[1])
        return FakeReply(self.data_xml)

    def close_session(self) -> None:
        self.closed = True


def _values(xml: str) -> dict[str, str]:
    root = ET.fromstring(xml)
    return {
        element.tag.rsplit("}", 1)[-1]: (element.text or "").strip()
        for element in root.iter()
    }


def _tags(xml: str) -> set[str]:
    return {
        element.tag.rsplit("}", 1)[-1] for element in ET.fromstring(xml).iter()
    }


def _patch_connect(monkeypatch, manager: FakeManager, captured: dict) -> None:
    def connect(**kwargs):
        captured.update(kwargs)
        return manager

    monkeypatch.setattr("app.bras.netconf.ncclient_manager.connect", connect)


def test_connect_uses_netconf_defaults(monkeypatch) -> None:
    captured: dict = {}
    manager = FakeManager(USER_XML)
    _patch_connect(monkeypatch, manager, captured)

    settings = Settings(
        bras_host="198.51.100.1",
        netconf_user="monitor",
        netconf_password="secret",
        netconf_timeout=7,
    )
    client = BrasClient(settings).connect()

    assert captured["host"] == "198.51.100.1"
    assert captured["port"] == 830
    assert captured["username"] == "monitor"
    assert captured["password"] == "secret"
    assert captured["timeout"] == 7
    assert "device_params" not in captured
    assert client.connected is True


def test_get_access_user_returns_parsed_result(monkeypatch) -> None:
    manager = FakeManager(USER_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    result = client.get_access_user("usuario_prueba")

    assert result.state == "ok"
    assert result.user_id == 21747
    assert "usuario_prueba" in manager.filters[-1]


def test_offline_history_returns_parsed_records(monkeypatch) -> None:
    manager = FakeManager(OFFLINE_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    records = client.offline_history("usuario_prueba", 5)

    assert len(records) == 5
    assert "online-fail-or-offline-record" in _tags(manager.filters[-1])
    assert _values(manager.filters[-1])["view-count"] == "5"


def test_qos_counters_uses_access_index_filter(monkeypatch) -> None:
    manager = FakeManager(QOS_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    assert client.qos_counters(21747) == (8_941_651_101, 43_149_452_521)
    assert _values(manager.filters[-1])["id"] == "21747"
    assert "offline-record" not in _tags(manager.filters[-1])


def test_offline_history_rejects_invalid_count(monkeypatch) -> None:
    manager = FakeManager(OFFLINE_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    with pytest.raises(ValueError):
        client.offline_history("usuario_prueba", 0)


def test_qos_rejects_invalid_access_index(monkeypatch) -> None:
    manager = FakeManager(QOS_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    with pytest.raises(ValueError):
        client.qos_counters(-1)


def test_close_closes_netconf_session(monkeypatch) -> None:
    manager = FakeManager(USER_XML)
    _patch_connect(monkeypatch, manager, {})

    client = BrasClient(Settings()).connect()
    client.close()

    assert manager.closed is True
