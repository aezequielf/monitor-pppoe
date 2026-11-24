"""Fachada BRAS: NETCONF para sesión/QoS y SNMP para métricas del NAS."""

from __future__ import annotations

import re

from ..config import Settings
from ..schemas import HistoryDisconnection, SystemInfo
from .netconf import NetconfClient
from .parser import parse_access_user, parse_offline_records, parse_qos_counters
from .snmp import SnmpClient


class BrasClient:
    """Cliente por lease: una sesión NETCONF y consultas SNMP bajo demanda."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._netconf = NetconfClient(settings)
        self._snmp = SnmpClient(settings)

    @property
    def connected(self) -> bool:
        return self._netconf.connected

    def connect(self) -> "BrasClient":
        self._netconf.connect()
        return self

    def validate_username(self, username: str) -> None:
        if not re.fullmatch(self._settings.username_regex, username):
            raise ValueError("Nombre de usuario inválido")

    def get_access_user(self, username: str):
        self.validate_username(username)
        return parse_access_user(self._netconf.get_access_user(username))

    def offline_history(self, username: str, count: int) -> list[HistoryDisconnection]:
        self.validate_username(username)
        if not isinstance(count, int) or count < 1:
            raise ValueError("Cantidad de desconexiones inválida")
        return parse_offline_records(
            self._netconf.get_offline_records(username, count)
        )

    def qos_counters(self, access_index: int) -> tuple[int | None, int | None]:
        if not isinstance(access_index, int) or access_index < 0:
            raise ValueError("Access index inválido")
        return parse_qos_counters(self._netconf.get_qos(access_index))

    async def cpu_usage(self) -> int | None:
        return await self._snmp.cpu_usage()

    async def memory_usage(self) -> int | None:
        return await self._snmp.memory_usage()

    async def online_users(self) -> int | None:
        return await self._snmp.online_users()

    async def system_info(self) -> SystemInfo:
        return await self._snmp.system_info()

    def close(self) -> None:
        self._netconf.close()

    async def aclose(self) -> None:
        self.close()
        await self._snmp.close()

    def __enter__(self) -> "BrasClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()
