from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.bras.parser import (
    parse_access_user,
    parse_qos_pass_bytes,
    to_snapshot,
)
from app.schemas import LatestSample

FIXTURES = Path(__file__).parent / "fixtures"
RAW = FIXTURES / "salida.txt"
QOS_OUT = FIXTURES / "qos_outbound.txt"
QOS_IN = FIXTURES / "qos_inbound.txt"


@pytest.fixture
def raw() -> str:
    return RAW.read_text(encoding="utf-8")


def test_parse_ok_static_fields(raw: str) -> None:
    result = parse_access_user(raw)

    assert result.state == "ok"
    assert result.error_msg is None
    assert result.user_id == 10001
    assert result.static is not None
    assert result.static.mac == "aabb-ccdd-eeff"
    assert result.static.ip == "203.0.113.10"
    assert result.static.start_time == "2026-01-01 00:00:00"
    assert result.static.in_qos == "plan_demo(Radius)"
    assert result.static.out_qos == "plan_demo(Radius)"
    assert result.static.in_pir_kbps == 112640
    assert result.static.out_cir_kbps == 215040


def test_parse_does_not_build_rate_sample(raw: str) -> None:
    assert parse_access_user(raw).latest is None


def test_parse_qos_outbound() -> None:
    raw = QOS_OUT.read_text(encoding="utf-8")
    assert parse_qos_pass_bytes(raw) == 43_149_452_521


def test_parse_qos_inbound() -> None:
    raw = QOS_IN.read_text(encoding="utf-8")
    assert parse_qos_pass_bytes(raw) == 8_941_651_101


def test_parse_qos_without_classes_uses_first_pass_line() -> None:
    raw = """
 user-id 17 inbound user-car statistics:
  Pass:                            1,380,789 packets,                  1,938,627,756 bytes
  Discard:                         817,891 packets,                    1,148,318,964 bytes
"""
    assert parse_qos_pass_bytes(raw) == 1_938_627_756


def test_parse_qos_invalid_output() -> None:
    assert parse_qos_pass_bytes("") is None
    assert parse_qos_pass_bytes("Total users : 1") is None


def test_parse_qos_without_total_does_not_use_partial_class() -> None:
    raw = """
 [be]
  Pass:                            1,380,789 packets,                  1,938,627,756 bytes
 [af1]
  Pass:                                1,000 packets,                      1,000 bytes
"""
    assert parse_qos_pass_bytes(raw) is None


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
    result = parse_access_user(raw)
    result.latest = LatestSample(
        ts=moment,
        up_mbps=3.2,
        down_mbps=12.8,
        up_bytes=8_941_651_101,
        down_bytes=43_149_452_521,
    )
    snapshot = to_snapshot("usuario", result, version=7)

    assert snapshot.username == "usuario"
    assert snapshot.version == 7
    assert snapshot.online is True
    assert snapshot.state == "ok"
    assert snapshot.latest is not None
    assert snapshot.latest.ts == moment
