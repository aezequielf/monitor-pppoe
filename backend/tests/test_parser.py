from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.bras.parser import kbyte_to_mbps, parse_access_user, to_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "salida.txt"

EXPECTED_MBPS = 2 * 1024 * 8 / 60 / 1_000_000


@pytest.fixture
def raw() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_ok_static_fields(raw: str) -> None:
    result = parse_access_user(raw)

    assert result.state == "ok"
    assert result.error_msg is None
    assert result.static is not None
    assert result.static.mac == "7817-be3f-b60d"
    assert result.static.ip == "200.49.122.133"
    assert result.static.start_time == "2026-10-14 07:11:43"
    assert result.static.in_qos == "fo_200_megas(Radius)"
    assert result.static.out_qos == "fo_200_megas(Radius)"
    assert result.static.in_pir_kbps == 112640
    assert result.static.out_cir_kbps == 215040


def test_parse_ok_realtime_speeds(raw: str) -> None:
    result = parse_access_user(raw)

    assert result.latest is not None
    assert result.latest.in_raw == 2.0
    assert result.latest.out_raw == 2.0
    assert result.latest.in_unit == "kbyte/min"
    assert result.latest.out_unit == "kbyte/min"
    # inbound = subida, outbound = bajada (punto de vista del BRAS)
    assert result.latest.up_mbps == pytest.approx(EXPECTED_MBPS)
    assert result.latest.down_mbps == pytest.approx(EXPECTED_MBPS)


def test_direction_is_configurable(raw: str) -> None:
    swapped = parse_access_user(raw, up_field="outbound", down_field="inbound")
    assert swapped.state == "ok"
    assert swapped.latest is not None
    assert swapped.latest.in_raw == 2.0
    assert swapped.latest.out_raw == 2.0


def test_sin_conexion_when_no_block() -> None:
    assert parse_access_user("").state == "sin_conexion"
    assert parse_access_user("Error: The user does not exist.").state == "sin_conexion"


def test_multiple_sessions_is_error(raw: str) -> None:
    result = parse_access_user(raw + "\n" + raw)
    assert result.state == "error"
    assert result.error_msg is not None
    assert "Múltiples" in result.error_msg


def test_to_snapshot(raw: str) -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = parse_access_user(raw, now=moment)
    snapshot = to_snapshot("usuario", result, version=7)

    assert snapshot.username == "usuario"
    assert snapshot.version == 7
    assert snapshot.online is True
    assert snapshot.state == "ok"
    assert snapshot.latest is not None
    assert snapshot.latest.ts == moment


def test_kbyte_to_mbps() -> None:
    assert kbyte_to_mbps(None) is None
    assert kbyte_to_mbps(2.0) == pytest.approx(EXPECTED_MBPS)
    assert kbyte_to_mbps(1.0, time_base=1) == pytest.approx(1024 * 8 / 1_000_000)
