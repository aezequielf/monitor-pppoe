from __future__ import annotations

import pytest

from app.history import ConnectionHistoryError, parse_connection_history


def test_parse_connection_history_limits_and_fields() -> None:
    payload = {
        "status": "ok",
        "resultado": [
            {
                "inicio": "2026-11-06 09:37:29",
                "final": "2026-11-06 14:40:09",
                "upload": "1234567",
                "download": "9876543210",
                "nas": "200.49.120.109",
                "causa": "",
                "mac": "28:41:EC:AB:C9:46",
                "ip": "179.60.100.109",
            },
            {
                "inicio": "2026-11-05 09:00:00",
                "final": "",
                "upload": "0",
                "download": "0",
                "nas": "200.49.120.109",
                "causa": "",
                "mac": "28:41:EC:AB:C9:46",
                "ip": "179.60.100.109",
            },
        ],
    }

    records = parse_connection_history(payload, limit=1)

    assert len(records) == 1
    record = records[0]
    assert record.start == "2026-11-06 09:37:29"
    assert record.end == "2026-11-06 14:40:09"
    assert record.duration_seconds == 18_160
    assert record.upload_bytes == 1_234_567
    assert record.download_bytes == 9_876_543_210
    assert record.nas == "200.49.120.109"
    assert record.reason is None
    assert record.mac == "28:41:EC:AB:C9:46"
    assert record.ip == "179.60.100.109"


def test_parse_connection_history_active_has_no_duration() -> None:
    payload = {
        "status": "ok",
        "resultado": [
            {
                "inicio": "2026-11-06 09:37:29",
                "final": "",
                "upload": "0",
                "download": "0",
                "nas": "200.49.120.109",
                "causa": "",
                "mac": "28:41:EC:AB:C9:46",
                "ip": "179.60.100.109",
            }
        ],
    }

    record = parse_connection_history(payload)[0]

    assert record.end is None
    assert record.duration_seconds is None


def test_parse_connection_history_empty_result() -> None:
    payload = {
        "status": "ok",
        "resultado": " No se encontraron conexiones para usuario01",
    }

    assert parse_connection_history(payload) == []


def test_parse_connection_history_invalid_payload() -> None:
    with pytest.raises(ConnectionHistoryError):
        parse_connection_history([])
    with pytest.raises(ConnectionHistoryError):
        parse_connection_history({"status": "error", "resultado": "falló"})
    with pytest.raises(ConnectionHistoryError):
        parse_connection_history({"status": "ok", "resultado": {"inicio": "x"}})
