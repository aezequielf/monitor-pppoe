from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.bras.parser import (
    parse_access_user_summary,
    parse_cpu_usage,
    parse_memory_usage,
)
from app.monitor.poller import _has_changed
from app.schemas import HostMetrics, LatestSample, ParseResult

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_cpu_usage() -> None:
    raw = (FIXTURES / "cpu_usage.txt").read_text(encoding="utf-8")
    assert parse_cpu_usage(raw) == 14


def test_parse_memory_usage() -> None:
    raw = (FIXTURES / "memory_usage.txt").read_text(encoding="utf-8")
    assert parse_memory_usage(raw) == 14


def test_parse_access_user_summary() -> None:
    raw = (FIXTURES / "access_user_summary.txt").read_text(encoding="utf-8")
    assert parse_access_user_summary(raw) == 8566


@pytest.mark.parametrize(
    "parser",
    [parse_cpu_usage, parse_memory_usage, parse_access_user_summary],
)
def test_parsers_return_none_on_unknown_output(parser) -> None:
    assert parser("salida inesperada") is None


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
