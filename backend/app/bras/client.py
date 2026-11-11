"""Cliente Netmiko para el BRAS: conexión persistente y consultas."""

from __future__ import annotations

import re
from typing import Optional

from netmiko import ConnectHandler

from ..config import Settings
from .parser import (
    parse_access_user_summary,
    parse_cpu_usage,
    parse_memory_usage,
    parse_qos_pass_bytes,
)


class BrasClient:
    """Mantiene una única sesión SSH y reusa el canal entre consultas."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn = None

    @property
    def connected(self) -> bool:
        if self._conn is None:
            return False
        try:
            return bool(self._conn.is_alive())
        except Exception:  # pragma: no cover - defensivo
            return False

    def connect(self) -> "BrasClient":
        s = self._settings
        kwargs = {
            "device_type": s.bras_device_type,
            "host": s.bras_host,
            "port": s.bras_port,
            "username": s.bras_user,
            "password": s.bras_password,
            "conn_timeout": s.bras_conn_timeout,
            "read_timeout_override": s.bras_read_timeout,
        }
        if s.bras_secret:
            kwargs["secret"] = s.bras_secret

        self._conn = ConnectHandler(**kwargs)
        if s.bras_secret:
            try:
                self._conn.enable()
            except Exception:
                pass
        try:
            self._conn.send_command(
                "screen-length 0 temporary", read_timeout=s.bras_read_timeout
            )
        except Exception:
            pass
        return self

    def _ensure_connected(self) -> None:
        if not self.connected:
            self.close()
            self.connect()

    def validate_username(self, username: str) -> None:
        if not re.fullmatch(self._settings.username_regex, username):
            raise ValueError("Nombre de usuario inválido")

    def _send(self, command: str) -> str:
        self._ensure_connected()
        try:
            return self._conn.send_command(
                command, read_timeout=self._settings.bras_read_timeout
            )
        except Exception:
            # Un reintento tras reconectar ante un corte transitorio.
            self.close()
            self.connect()
            return self._conn.send_command(
                command, read_timeout=self._settings.bras_read_timeout
            )

    def query(self, username: str) -> str:
        """Ejecuta el comando de monitoreo y devuelve la salida cruda."""
        self.validate_username(username)
        command = self._settings.command_template.format(username=username)
        return self._send(command)

    def _qos_pass_bytes(self, template: str, user_id: int) -> int | None:
        if not isinstance(user_id, int) or user_id < 0:
            raise ValueError("UserID inválido")
        return parse_qos_pass_bytes(self._send(template.format(user_id=user_id)))

    def qos_inbound(self, user_id: int) -> int | None:
        return self._qos_pass_bytes(self._settings.qos_inbound_command, user_id)

    def qos_outbound(self, user_id: int) -> int | None:
        return self._qos_pass_bytes(self._settings.qos_outbound_command, user_id)

    def offline_history(self, username: str, count: int) -> str:
        """Consulta las últimas desconexiones registradas por el BRAS."""
        self.validate_username(username)
        if not isinstance(count, int) or count < 1:
            raise ValueError("Cantidad de desconexiones inválida")
        command = self._settings.offline_history_command.format(
            username=username, count=count
        )
        return self._send(command)

    def cpu_usage(self) -> int | None:
        return parse_cpu_usage(self._send(self._settings.cpu_command))

    def memory_usage(self) -> int | None:
        return parse_memory_usage(self._send(self._settings.memory_command))

    def online_users(self) -> int | None:
        return parse_access_user_summary(self._send(self._settings.users_command))

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.disconnect()
            except Exception:
                pass
            finally:
                self._conn = None

    def __enter__(self) -> "BrasClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()
