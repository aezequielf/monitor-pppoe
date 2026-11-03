"""Cliente Netmiko para el BRAS: conexión persistente y consultas."""

from __future__ import annotations

import re
from typing import Optional

from netmiko import ConnectHandler

from ..config import Settings


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
            "read_timeout": s.bras_read_timeout,
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

    def query(self, username: str) -> str:
        """Ejecuta el comando de monitoreo y devuelve la salida cruda."""
        self.validate_username(username)
        self._ensure_connected()
        command = self._settings.command_template.format(username=username)
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
