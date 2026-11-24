from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.bras.parser import (
    parse_access_user,
    parse_offline_records,
    parse_qos_counters,
    to_snapshot,
)
from app.schemas import LatestSample

FIXTURES = Path(__file__).parent / "fixtures"
USER = FIXTURES / "access_user.xml"
USER_MULTI = FIXTURES / "access_user_multi.xml"
QOS = FIXTURES / "qos_counters.xml"
OFFLINE = FIXTURES / "offline_records.xml"

EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <bras-user-manage xmlns="urn:huawei:yang:huawei-bras-user-manage">
    <access-tables/>
  </bras-user-manage>
</data>
"""


def test_parse_ok_static_fields() -> None:
    result = parse_access_user(USER.read_text(encoding="utf-8"))

    assert result.state == "ok"
    assert result.error_msg is None
    assert result.user_id == 21747
    assert result.static is not None
    assert result.static.mac == "aabb-ccdd-eeff"
    assert result.static.ip == "203.0.113.10"
    assert result.static.start_time == "2026-01-01 00:00:00"
    assert result.static.in_qos is None
    assert result.static.out_qos is None
    assert result.static.in_pir_kbps is None
    assert result.static.out_cir_kbps is None


def test_parse_does_not_build_rate_sample() -> None:
    assert parse_access_user(USER.read_text(encoding="utf-8")).latest is None


def test_parse_qos_counters() -> None:
    up, down = parse_qos_counters(QOS.read_text(encoding="utf-8"))

    assert up == 8_941_651_101
    assert down == 43_149_452_521


def test_parse_qos_without_total_does_not_use_partial_class() -> None:
    xml = """<?xml version="1.0"?>
<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <qos xmlns="urn:huawei:yang:huawei-qos">
    <global-query><user-informations><user-information>
      <direction>inbound</direction>
      <user-queue-statisticss>
        <user-queue-statistics>
          <service-class>be</service-class><pass-bytes>123</pass-bytes>
        </user-queue-statistics>
        <user-queue-statistics>
          <service-class>af1</service-class><pass-bytes>456</pass-bytes>
        </user-queue-statistics>
      </user-queue-statisticss>
    </user-information></user-informations></global-query>
  </qos>
</data>
"""
    assert parse_qos_counters(xml) == (None, None)


def test_parse_offline_records() -> None:
    records = parse_offline_records(OFFLINE.read_text(encoding="utf-8"))

    assert len(records) == 5
    assert records[0].start == "2026-11-06 09:37:29"
    assert records[0].end == "2026-11-06 14:40:09"
    assert records[0].duration_seconds == 18_160
    assert records[0].reason == "PPP with echo fail"
    assert records[0].mac == "aabb-ccdd-eeff"
    assert records[0].ip == "203.0.113.10"
    assert records[0].interface is None
    assert records[-1].reason == "PPP with echo fail"


def test_parse_offline_records_invalid_output() -> None:
    assert parse_offline_records(EMPTY) == []


def test_sin_conexion_when_no_access_table() -> None:
    assert parse_access_user(EMPTY).state == "sin_conexion"


def test_multiple_sessions_is_error() -> None:
    result = parse_access_user(USER_MULTI.read_text(encoding="utf-8"))

    assert result.state == "error"
    assert result.error_msg is not None
    assert "Múltiples" in result.error_msg


def test_to_snapshot() -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = parse_access_user(USER.read_text(encoding="utf-8"))
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
