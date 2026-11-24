"""Cliente NETCONF para consultas de sesión, histórico y QoS."""

from __future__ import annotations

from ncclient import manager as ncclient_manager

from ..config import Settings
from .xml_filters import access_user_filter, offline_records_filter, qos_filter


class NetconfClient:
    """Mantiene una sesión NETCONF por lease."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._manager = None

    @property
    def connected(self) -> bool:
        if self._manager is None:
            return False
        return bool(getattr(self._manager, "connected", True))

    def connect(self) -> "NetconfClient":
        self.close()
        s = self._settings
        host = s.netconf_host or s.bras_host
        self._manager = ncclient_manager.connect(
            host=host,
            port=s.netconf_port,
            username=s.netconf_user or s.bras_user,
            password=s.netconf_password or s.bras_password,
            timeout=s.netconf_timeout,
            allow_agent=False,
            look_for_keys=False,
            hostkey_verify=False,
        )
        return self

    def _get(self, filter_xml: str) -> str:
        if not self.connected:
            self.connect()
        try:
            reply = self._manager.get(filter=("subtree", filter_xml))
        except Exception:
            self.close()
            self.connect()
            reply = self._manager.get(filter=("subtree", filter_xml))
        if not reply.ok:
            raise RuntimeError(f"Falló la consulta NETCONF: {reply.error}")
        return reply.data_xml

    def get_access_user(self, username: str) -> str:
        return self._get(access_user_filter(username))

    def get_offline_records(self, username: str, count: int) -> str:
        return self._get(offline_records_filter(username, count))

    def get_qos(self, access_index: int) -> str:
        return self._get(qos_filter(access_index))

    def close(self) -> None:
        manager = self._manager
        self._manager = None
        if manager is not None:
            try:
                manager.close_session()
            except Exception:
                pass
