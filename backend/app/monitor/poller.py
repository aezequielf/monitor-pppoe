"""Loop de consulta periódica del BRAS para un lease."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import anyio

from ..history import fetch_connection_history
from ..schemas import HostMetrics, LatestSample, MonitorHistory, ParseResult
from .lease import Lease, LeaseManager, _close_client
from .rates import RateTracker

QOS_MISSING_MESSAGE = (
    "El usuario no tiene contadores QoS disponibles para este tipo de monitoreo."
)


def _has_changed(previous, result: ParseResult) -> bool:
    if previous is None:
        return True
    if previous.state != result.state:
        return True
    if previous.static != result.static:
        return True
    if (previous.host or HostMetrics()) != (result.host or HostMetrics()):
        return True
    if previous.latest is None or result.latest is None:
        return previous.latest is not result.latest
    return (
        previous.latest.up_mbps != result.latest.up_mbps
        or previous.latest.down_mbps != result.latest.down_mbps
    )


async def load_history(manager: LeaseManager, lease: Lease, client) -> None:
    history = MonitorHistory()

    try:
        history.disconnections = await anyio.to_thread.run_sync(
            client.offline_history, lease.username, manager.settings.history_limit
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        history.disconnections_error = f"No se pudo consultar NETCONF: {exc}"

    try:
        history.connections = await fetch_connection_history(
            lease.username,
            manager.settings,
            limit=manager.settings.history_limit,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        history.connections_error = str(exc)

    manager.publish_history(lease, history)


def _query_qos(client, access_index: int) -> tuple[int | None, float, int | None, float]:
    up_bytes, down_bytes = client.qos_counters(access_index)
    ts = time.monotonic()
    return up_bytes, ts, down_bytes, ts


def _remaining_poll_delay(cycle_started: float, interval: float) -> float:
    """Descuenta del intervalo el tiempo consumido por los comandos del ciclo."""
    return max(0.0, interval - (time.monotonic() - cycle_started))


async def _fetch_host_metrics(client) -> HostMetrics:
    return HostMetrics(
        cpu_percent=await client.cpu_usage(),
        memory_percent=await client.memory_usage(),
        online_users=await client.online_users(),
    )


async def run_poller(manager: LeaseManager, lease: Lease) -> None:
    settings = manager.settings
    client = lease.client
    result = lease.initial_result
    if result is None:
        return

    access_index = result.user_id if result.state == "ok" else None
    rates = RateTracker()
    host = HostMetrics()
    last_snmp_update = 0.0

    try:
        while not lease.stop_event.is_set():
            cycle_started = time.monotonic()
            if (
                last_snmp_update == 0.0
                or cycle_started - last_snmp_update >= settings.snmp_poll_interval
            ):
                try:
                    host = await _fetch_host_metrics(client)
                    last_snmp_update = cycle_started
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    manager.publish_error(lease, f"Error de SNMP: {exc}")
                    asyncio.create_task(manager.release(lease, reason="snmp_error"))
                    return

            result.host = host

            if access_index is not None and result.state == "ok":
                try:
                    up_bytes, up_ts, down_bytes, down_ts = (
                        await anyio.to_thread.run_sync(_query_qos, client, access_index)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    manager.publish_error(lease, f"Error de NETCONF: {exc}")
                    asyncio.create_task(manager.release(lease, reason="netconf_error"))
                    return

                if up_bytes is None or down_bytes is None:
                    manager.publish_error(lease, QOS_MISSING_MESSAGE)
                    asyncio.create_task(
                        manager.release(lease, reason="qos_missing")
                    )
                    return

                start_time = result.static.start_time if result.static else None
                up_mbps, down_mbps = rates.update(
                    up_bytes=up_bytes,
                    up_ts=up_ts,
                    down_bytes=down_bytes,
                    down_ts=down_ts,
                    session_key=f"{access_index}:{start_time}",
                )
                if up_mbps is not None and down_mbps is not None:
                    result.latest = LatestSample(
                        ts=datetime.now(timezone.utc),
                        up_mbps=up_mbps,
                        down_mbps=down_mbps,
                        up_bytes=up_bytes,
                        down_bytes=down_bytes,
                    )
            else:
                rates.reset()

            if settings.sample_mode == "every_poll" or _has_changed(
                lease.snapshot, result
            ):
                manager.publish_snapshot(lease, result)

            if result.state == "sin_conexion":
                await _close_client(client)
                lease.client = None
                lease.state = "sin_conexion"
                return

            delay = _remaining_poll_delay(cycle_started, settings.poll_interval)
            if delay <= 0:
                continue
            try:
                await asyncio.wait_for(lease.stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue
            else:
                return
    except asyncio.CancelledError:
        raise
