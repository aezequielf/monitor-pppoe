from __future__ import annotations

import pytest

from app import config as config_module
from app.auth import jwt as jwt_module
from app.auth import users


def test_load_settings_defaults_and_override(tmp_path) -> None:
    override = tmp_path / "config.py"
    override.write_text(
        "POLL_INTERVAL = 9\nMAX_SESIONES = 2\n"
        "QOS_INBOUND_COMMAND = 'display qos user-id {user_id} inbound'\n"
        "JWT_SECRET = 'x'\n",
        encoding="utf-8",
    )

    settings = config_module.load_settings(override)

    assert settings.poll_interval == 9
    assert settings.max_sesiones == 2
    assert settings.qos_inbound_command.endswith("inbound")
    # valores no sobreescritos conservan el default
    assert settings.qos_outbound_command.endswith("outbound | no-more")
    assert settings.session_ttl == 600


def test_sample_mode_validation(tmp_path) -> None:
    override = tmp_path / "config.py"
    override.write_text("JWT_SECRET = 'x'\nSAMPLE_MODE = 'invalido'\n", encoding="utf-8")

    with pytest.raises(Exception):
        config_module.load_settings(override)


def test_users_and_jwt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-012345678901234567890123456789")
    config_module.get_settings.cache_clear()

    users.init_db()
    users.create_user("alice", "secret-password")

    assert users.authenticate("alice", "secret-password") is True
    assert users.authenticate("alice", "wrong") is False
    assert users.authenticate("unknown", "secret-password") is False
    assert users.list_users() == ["alice"]

    with pytest.raises(ValueError):
        users.create_user("alice", "otra")

    access = jwt_module.create_access_token("alice")
    payload = jwt_module.decode_token(access, jwt_module.ACCESS)
    assert payload["sub"] == "alice"

    with pytest.raises(jwt_module.jwt.InvalidTokenError):
        jwt_module.decode_token(access, jwt_module.REFRESH)

    config_module.get_settings.cache_clear()
