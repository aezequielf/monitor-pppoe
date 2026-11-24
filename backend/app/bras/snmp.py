"""Cliente SNMP v2c para métricas del NAS e información del chasis."""

from __future__ import annotations

import re

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from ..config import Settings
from ..schemas import SystemInfo

OID_CHASSIS = "1.3.6.1.2.1.47.1.1.1.1.7.16777216"
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_CPU = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.16842753"
OID_MEMORY = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.16842753"
OID_ONLINE_USERS = "1.3.6.1.4.1.2011.5.25.40.1.1.20.1.5.71"

_VERSION_RE = re.compile(r"\bVersion\s+\S+\s+\(([^)]+)\)", re.IGNORECASE)
_VERSION_FALLBACK_RE = re.compile(r"\bVersion\s+(\S+)", re.IGNORECASE)
_CHASSIS_FALLBACK_RE = re.compile(r".*\b(HUAWEI\s+.+)$")


def parse_software_version(sys_descr: str | None) -> str | None:
    if not sys_descr:
        return None
    match = _VERSION_RE.search(sys_descr)
    if match:
        return match.group(1).strip()
    match = _VERSION_FALLBACK_RE.search(sys_descr)
    return match.group(1).strip() if match else None


def parse_chassis_name(sys_descr: str | None) -> str | None:
    if not sys_descr:
        return None
    match = _CHASSIS_FALLBACK_RE.search(sys_descr)
    return match.group(1).strip() if match else None


def _to_int(value) -> int | None:
    text = value.prettyPrint().strip()
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else None


def _to_text(value) -> str | None:
    text = value.prettyPrint().strip()
    return text or None


class SnmpClient:
    """Lee OIDs fijos usando community SNMP v2c."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: SnmpEngine | None = None

    def _ensure_engine(self) -> SnmpEngine:
        if self._engine is None:
            self._engine = SnmpEngine()
        return self._engine

    async def _get_value(self, oid: str):
        s = self._settings
        host = s.snmp_host or s.bras_host
        target = await UdpTransportTarget.create(
            (host, s.snmp_port), timeout=s.snmp_timeout, retries=s.snmp_retries
        )
        mp_model = 1 if s.snmp_version == 2 else 0
        response = await get_cmd(
            self._ensure_engine(),
            CommunityData(s.snmp_community, mpModel=mp_model),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        error_indication, error_status, error_index, var_binds = response
        if error_indication:
            raise RuntimeError(f"SNMP {oid}: {error_indication}")
        if error_status:
            raise RuntimeError(
                f"SNMP {oid}: {error_status.prettyPrint()} en {error_index}"
            )
        if not var_binds:
            raise RuntimeError(f"SNMP {oid}: respuesta vacía")
        return var_binds[0][1]

    async def get_int(self, oid: str) -> int | None:
        return _to_int(await self._get_value(oid))

    async def get_text(self, oid: str) -> str | None:
        return _to_text(await self._get_value(oid))

    async def cpu_usage(self) -> int | None:
        return await self.get_int(OID_CPU)

    async def memory_usage(self) -> int | None:
        return await self.get_int(OID_MEMORY)

    async def online_users(self) -> int | None:
        return await self.get_int(OID_ONLINE_USERS)

    async def system_info(self) -> SystemInfo:
        chassis = await self.get_text(OID_CHASSIS)
        sys_descr = await self.get_text(OID_SYS_DESCR)
        return SystemInfo(
            chassis_name=chassis or parse_chassis_name(sys_descr),
            software_version=parse_software_version(sys_descr),
        )

    async def close(self) -> None:
        if self._engine is not None:
            self._engine.close_dispatcher()
            self._engine = None
