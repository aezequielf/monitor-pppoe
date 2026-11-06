"""Parseo de las salidas del BRAS.

- `display access-user username <user> verbose`: datos estáticos y UserID.
- `display qos user-id <id> inbound|outbound`: contadores acumulados de bytes.

La tasa se calcula en `monitor/rates.py` a partir de esos contadores.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ..schemas import MonitorSnapshot, ParseResult, StaticInfo

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 3 and set(stripped) == {"-"}


def _split_blocks(raw: str) -> list[str]:
    """Devuelve los bloques que contienen el detalle de una sesión."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = "\n".join(current)
        if "user access index" in text.lower():
            blocks.append(text)
        current.clear()

    for line in lines:
        if _is_separator(line):
            flush()
            continue
        # Si el BRAS no separa con guiones, una nueva sesión reinicia en "Basic:".
        if line.strip().lower() == "basic:" and any(
            item.strip().lower() == "basic:" for item in current
        ):
            flush()
        current.append(line)

    flush()
    return blocks


def _parse_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def _text(fields: dict[str, str], key: str) -> Optional[str]:
    value = fields.get(key)
    if value is None:
        return None
    value = value.strip()
    if value in ("", "-"):
        return None
    return value


def _first_int(fields: dict[str, str], key: str) -> Optional[int]:
    value = _text(fields, key)
    if value is None:
        return None
    match = _NUMBER_RE.search(value)
    return int(float(match.group())) if match else None


def parse_access_user(raw: str) -> ParseResult:
    """Convierte la salida cruda del BRAS en un `ParseResult`.

    - 0 bloques  -> `sin_conexion` (usuario inexistente / sin sesión).
    - >1 bloques -> `error` (múltiples sesiones para el mismo usuario).
    - 1 bloque   -> `ok` con datos estáticos y `user_id`.
    """
    blocks = _split_blocks(raw)
    if not blocks:
        return ParseResult(state="sin_conexion")
    if len(blocks) > 1:
        return ParseResult(
            state="error",
            error_msg=f"Múltiples sesiones activas para el usuario ({len(blocks)})",
        )

    fields = _parse_fields(blocks[0])

    static = StaticInfo(
        mac=_text(fields, "user mac"),
        ip=_text(fields, "user ip address"),
        start_time=_text(fields, "access start time"),
        in_qos=_text(fields, "inbound qos-profile-name"),
        out_qos=_text(fields, "outbound qos-profile-name"),
        in_pir_kbps=_first_int(fields, "inbound pir"),
        out_cir_kbps=_first_int(fields, "outbound cir"),
    )

    return ParseResult(
        state="ok",
        static=static,
        user_id=_first_int(fields, "user access index"),
    )


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


# --- Métricas del NAS (CPU / memoria / usuarios online) ------------------

_CPU_RE = re.compile(
    r"System cpu use rate is\s*:\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
)
_MEMORY_RE = re.compile(
    r"Memory Using Percentage Is\s*:\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
)
_TOTAL_USERS_RE = re.compile(r"Total users\s*:\s*(\d+)", re.IGNORECASE)


def _percent(raw: str, pattern: re.Pattern[str]) -> Optional[int]:
    match = pattern.search(raw)
    if match is None:
        return None
    return int(round(float(match.group(1))))


def parse_cpu_usage(raw: str) -> Optional[int]:
    """Extrae `System cpu use rate is : NN%` de `display cpu-usage`."""
    return _percent(raw, _CPU_RE)


def parse_memory_usage(raw: str) -> Optional[int]:
    """Extrae `Memory Using Percentage Is: NN%` de `display memory-usage`."""
    return _percent(raw, _MEMORY_RE)


def parse_access_user_summary(raw: str) -> Optional[int]:
    """Extrae `Total users : N` de `display access-user summary`."""
    match = _TOTAL_USERS_RE.search(raw)
    return int(match.group(1)) if match else None


# --- Contadores QoS por usuario -----------------------------------------

_QOS_CLASS_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$", re.MULTILINE)
_QOS_PASS_RE = re.compile(
    r"^\s*Pass:\s*[\d,]+\s+packets,\s*([\d,]+)\s+bytes", re.MULTILINE
)


def _pass_bytes(block: str) -> Optional[int]:
    match = _QOS_PASS_RE.search(block)
    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


def parse_qos_pass_bytes(raw: str) -> Optional[int]:
    """Extrae los bytes acumulados del bloque `[total]` de `display qos user-id`.

    Si el equipo no muestra clases y devuelve directamente las estadísticas CAR,
    se usa la primera línea `Pass:` del bloque.
    """
    classes = list(_QOS_CLASS_RE.finditer(raw))
    for index, match in enumerate(classes):
        if match.group(1).strip().lower() != "total":
            continue
        end = classes[index + 1].start() if index + 1 < len(classes) else len(raw)
        return _pass_bytes(raw[match.end() : end])
    # Sin bloques de clase el equipo puede devolver directamente las
    # estadísticas CAR. Si hay clases pero falta `[total]`, no se adivina.
    return None if classes else _pass_bytes(raw)
