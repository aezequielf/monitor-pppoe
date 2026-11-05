"""Carga de configuración.

Precedencia: defaults del modelo -> `instance/config.py` -> variables de entorno.

`instance/config.py` contiene secretos, está gitignored y NO se pisa al
actualizar el código (opción A del diseño).
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend
DEFAULT_INSTANCE_CONFIG = BASE_DIR / "instance" / "config.py"
DEFAULT_DATABASE_PATH = BASE_DIR / "instance" / "bras_monitor.db"


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # --- BRAS ---
    bras_host: str = ""
    bras_port: int = 22
    bras_user: str = ""
    bras_password: str = ""
    bras_secret: str = ""
    bras_device_type: str = "huawei"
    bras_conn_timeout: int = 15
    bras_read_timeout: int = 30

    command_template: str = (
        "display access-user username {username} verbose nop | no-more"
    )
    cpu_command: str = "display cpu-usage | no-more"
    memory_command: str = "display memory-usage | no-more"
    users_command: str = "display access-user summary"
    username_regex: str = r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$"

    # --- Auth / JWT ---
    jwt_secret: str = ""
    jwt_alg: str = "HS256"
    access_ttl: int = 3600
    refresh_ttl: int = 86400
    cookie_secure: bool = False

    # --- Base de usuarios ---
    database_path: str = str(DEFAULT_DATABASE_PATH)

    # --- Monitor / lease ---
    max_sesiones: int = 1
    poll_interval: float = 5
    session_ttl: int = 600
    disconnect_grace: int = 10
    heartbeat_ttl: int = 45

    # --- Unidades / mapeo de dirección ---
    kbyte_unit_bytes: int = 1024
    kbyte_time_base: int = 60
    dir_up: str = "inbound"
    dir_down: str = "outbound"
    sample_mode: str = "on_change"

    # --- Búsqueda de usuarios online (webservice dialup del NAS) ---
    online_users_url: str = "http://10.10.10.2/dialup2/webserv/"
    online_users_nas_ip: str = "200.49.120.10"
    online_users_timeout: float = 5.0

    # --- CORS (apps externas en otro origen) ---
    cors_origins: list[str] = Field(default_factory=list)

    # --- Servido del frontend (solo conveniencia de desarrollo) ---
    # En producción el front lo sirve nginx y esto queda en False.
    serve_frontend: bool = False
    frontend_dir: str = str(BASE_DIR.parent / "frontend")

    @field_validator("sample_mode")
    @classmethod
    def _validate_sample_mode(cls, value: str) -> str:
        if value not in ("on_change", "every_poll"):
            raise ValueError("SAMPLE_MODE debe ser 'on_change' o 'every_poll'")
        return value

    def validate_for_run(self) -> None:
        problems: list[str] = []
        if not self.jwt_secret or self.jwt_secret.startswith("CAMBIAR"):
            problems.append(
                "JWT_SECRET no configurado (editá backend/instance/config.py)"
            )
        if self.max_sesiones < 1:
            problems.append("MAX_SESIONES debe ser >= 1")
        if problems:
            raise RuntimeError("Configuración inválida: " + "; ".join(problems))


def _load_config_file(path: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("bras_monitor_local_config", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise RuntimeError(f"No se pudo cargar la configuración: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: getattr(module, name) for name in dir(module) if name.isupper()}


def load_settings(config_path: str | Path | None = None) -> Settings:
    if config_path is not None:
        path = Path(config_path)
    else:
        path = Path(os.environ.get("BRAS_MONITOR_CONFIG") or DEFAULT_INSTANCE_CONFIG)

    values: dict[str, Any] = {}
    if path.exists():
        values.update({k.lower(): v for k, v in _load_config_file(path).items()})

    # Variables de entorno ganan sobre el archivo (útil para systemd).
    for field_name in Settings.model_fields:
        if field_name == "cors_origins":
            continue
        env_value = os.environ.get(field_name.upper())
        if env_value is not None:
            values[field_name] = env_value

    return Settings(**values)


@lru_cache
def get_settings() -> Settings:
    return load_settings()
