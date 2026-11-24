from __future__ import annotations

from datetime import datetime, timezone

from app.bras.snmp import parse_chassis_name, parse_software_version
from app.monitor.poller import _has_changed
from app.schemas import HostMetrics, LatestSample, ParseResult

SYS_DESCR = (
    "Huawei Versatile Routing Platform Software VRP (R) software, "
    "Version 8.230 (NetEngine 8000 V800R023C00SPC500) Copyright (C) 2012-2023 "
    "Huawei Technologies Co., Ltd. HUAWEI NetEngine 8000 F1A-8H20Q"
)


def test_parse_software_version() -> None:
    assert parse_software_version(SYS_DESCR) == "NetEngine 8000 V800R023C00SPC500"
    assert parse_software_version(None) is None


def test_parse_chassis_name() -> None:
    assert parse_chassis_name(SYS_DESCR) == "HUAWEI NetEngine 8000 F1A-8H20Q"
    assert parse_chassis_name(None) is None


def _result(cpu: int) -> ParseResult:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ParseResult(
        state="ok",
        latest=LatestSample(ts=ts, up_bytes=1, down_bytes=2),
        host=HostMetrics(cpu_percent=cpu, memory_percent=20, online_users=100),
    )


def test_host_change_is_detected_even_with_same_traffic() -> None:
    assert _has_changed(_result(10), _result(11))
    assert not _has_changed(_result(10), _result(10))
