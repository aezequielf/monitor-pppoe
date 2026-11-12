"""Loop de consulta periódica del BRAS para un lease."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import anyio

from ..bras.parser import parse_access_user, parse_offline_records
from ..history import fetch_connection_history
from ..schemas import HostMetrics, LatestSample, MonitorHistory, ParseResult
from .lease import Lease, LeaseManager
from .rates import RateTracker

QOS_MISSING_MESSAGE = (
    "El usuario no tiene un perfil de QoS asignado para este tipo de monitoreo."
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


def _optional(call):
    try:
        return call()
    except Exception:
        return None


def _query_bundle(client, username: str) -> tuple[str, HostMetrics]:
    """Consulta el abonado y, sin cortar la sesión, las métricas del NAS."""
    raw = client.query(username)
    host = HostMetrics(
        cpu_percent=_optional(lambda: client.cpu_usage()),
        memory_percent=_optional(lambda: client.memory_usage()),
        online_users=_optional(lambda: client.online_users()),
    )
    return raw, host


async def _load_history(
    manager: LeaseManager, lease: Lease, client
) -> None:
    """Carga una sola vez el histórico del BRAS y de la API Radius."""
    history = MonitorHistory()

    try:
        raw = await anyio.to_thread.run_sync(
            client.offline_history, lease.username, manager.settings.history_limit
        )
        history.disconnections = parse_offline_records(raw)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - el histórico es auxiliar
        history.disconnections_error = f"No se pudo consultar el BRAS: {exc}"

    try:
        history.connections = await fetch_connection_history(
            lease.username,
            manager.settings,
            limit=manager.settings.history_limit,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - el histórico es auxiliar
        history.connections_error = str(exc)

    manager.publish_history(lease, history)


def _query_qos(client, user_id: int) -> tuple[int | None, float, int | None, float]:
    """Consulta los contadores QoS y registra el instante de cada muestra.

    Un `None` significa que el comando no devolvió una salida parseable: el
    usuario no tiene QoS asignado para esa dirección. Los errores de conexión
    se propagan para que el poller los trate como fallo SSH.
    """
    up_bytes = client.qos_inbound(user_id)
    up_ts = time.monotonic()
    down_bytes = client.qos_outbound(user_id)
    down_ts = time.monotonic()
    return up_bytes, up_ts, down_bytes, down_ts


def _remaining_poll_delay(cycle_started: float, interval: float) -> float:
    """Descuenta del intervalo el tiempo consumido por los comandos del ciclo."""
    return max(0.0, interval - (time.monotonic() - cycle_started))


async def run_poller(manager: LeaseManager, lease: Lease) -> None:
    settings = manager.settings
    client = lease.client
    user_id: int | None = None
    history_loaded = False
    rates = RateTracker()

    try:
        while not lease.stop_event.is_set():
            cycle_started = time.monotonic()
            try:
                raw, host = await anyio.to_thread.run_sync(
                    _query_bundle, client, lease.username
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                manager.publish_error(lease, f"Error de SSH: {exc}")
                # No esperamos aquí: `release` cancelaría esta misma tarea.
                asyncio.create_task(manager.release(lease, reason="ssh_error"))
                return

            result = parse_access_user(raw)
            result.host = host
            if user_id is None:
                user_id = result.user_id

            if user_id is not None and result.state == "ok":
                try:
                    up_bytes, up_ts, down_bytes, down_ts = (
                        await anyio.to_thread.run_sync(_query_qos, client, user_id)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    manager.publish_error(lease, f"Error de SSH: {exc}")
                    asyncio.create_task(manager.release(lease, reason="ssh_error"))
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
                    session_key=f"{user_id}:{start_time}",
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

            if result.state == "ok" and not history_loaded:
                history_loaded = True
                await _load_history(manager, lease, client)

            if result.state == "sin_conexion":
                # Usuario inexistente / sin sesión: cortar poller y cerrar SSH,
                # pero mantener el lease hasta que venza o el operador lo cierre.
                await anyio.to_thread.run_sync(client.close)
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
