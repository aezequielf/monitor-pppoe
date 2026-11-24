"""Parseo de respuestas XML de NETCONF del BRAS."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

from ..schemas import (
    HistoryDisconnection,
    MonitorSnapshot,
    ParseResult,
    StaticInfo,
)


def _text(value: str | None) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _duration_seconds(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    seconds = int((end_dt - start_dt).total_seconds())
    return seconds if seconds >= 0 else None


def parse_access_user(xml: str) -> ParseResult:
    root = ET.fromstring(xml)
    tables = root.findall(".//{*}access-table")
    if not tables:
        return ParseResult(state="sin_conexion")
    if len(tables) > 1:
        return ParseResult(
            state="error",
            error_msg=f"Múltiples sesiones activas para el usuario ({len(tables)})",
        )

    table = tables[0]
    basic = table.find(".//{*}access-user-basic-info")
    static = StaticInfo(
        mac=_text(basic.findtext("{*}access-mac-address")) if basic is not None else None,
        ip=_text(basic.findtext("{*}access-ipaddress")) if basic is not None else None,
        start_time=_text(basic.findtext("{*}access-start-time"))
        if basic is not None
        else None,
    )
    raw_index = _text(table.findtext("{*}access-index"))
    user_id = int(raw_index) if raw_index and raw_index.isdigit() else None
    return ParseResult(state="ok", static=static, user_id=user_id)


def parse_offline_records(xml: str) -> list[HistoryDisconnection]:
    root = ET.fromstring(xml)
    records: list[HistoryDisconnection] = []
    for record in root.findall(".//{*}online-fail-or-offline-record"):
        start = _text(record.findtext("{*}login-time"))
        end = _text(record.findtext("{*}offline-time"))
        records.append(
            HistoryDisconnection(
                start=start,
                end=end,
                duration_seconds=_duration_seconds(start, end),
                reason=_text(record.findtext("{*}online-fail-or-offline-reason")),
                mac=_text(record.findtext("{*}mac-address")),
                ip=_text(record.findtext("{*}ipv4-address")),
            )
        )
    return records


def parse_qos_counters(xml: str) -> tuple[int | None, int | None]:
    root = ET.fromstring(xml)
    up_bytes: int | None = None
    down_bytes: int | None = None
    for user in root.findall(".//{*}user-information"):
        direction = _text(user.findtext("{*}direction"))
        for stat in user.findall(".//{*}user-queue-statistics"):
            service_class = _text(stat.findtext("{*}service-class"))
            if service_class and service_class.lower() != "total":
                continue
            raw_bytes = _text(stat.findtext("{*}pass-bytes"))
            if not raw_bytes or not raw_bytes.isdigit():
                continue
            value = int(raw_bytes)
            if direction == "inbound" and up_bytes is None:
                up_bytes = value
            elif direction == "outbound" and down_bytes is None:
                down_bytes = value
    return up_bytes, down_bytes


def to_snapshot(
    username: str,
    result: ParseResult,
    *,
    version: int = 0,
    collected_at: Optional[datetime] = None,
) -> MonitorSnapshot:
    return MonitorSnapshot(
        username=username,
        online=result.state in ("ok", "error"),
        state=result.state,
        error_msg=result.error_msg,
        version=version,
        collected_at=collected_at or datetime.now(timezone.utc),
        static=result.static,
        latest=result.latest,
        host=result.host,
    )
