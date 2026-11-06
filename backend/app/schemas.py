"""Modelos Pydantic compartidos."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class StaticInfo(BaseModel):
    mac: Optional[str] = None
    ip: Optional[str] = None
    start_time: Optional[str] = None
    in_qos: Optional[str] = None
    out_qos: Optional[str] = None
    in_pir_kbps: Optional[int] = None
    out_cir_kbps: Optional[int] = None


class LatestSample(BaseModel):
    ts: datetime
    up_mbps: Optional[float] = None      # inbound (punto de vista del BRAS)
    down_mbps: Optional[float] = None    # outbound
    up_bytes: Optional[int] = None       # contador acumulado QoS
    down_bytes: Optional[int] = None


class HostMetrics(BaseModel):
    cpu_percent: Optional[int] = None
    memory_percent: Optional[int] = None
    online_users: Optional[int] = None


class ParseResult(BaseModel):
    state: Literal["ok", "sin_conexion", "error"]
    error_msg: Optional[str] = None
    static: Optional[StaticInfo] = None
    latest: Optional[LatestSample] = None
    host: Optional[HostMetrics] = None
    user_id: Optional[int] = None


class MonitorSnapshot(BaseModel):
    username: str
    online: bool
    state: Literal["ok", "sin_conexion", "error"]
    error_msg: Optional[str] = None
    version: int = 0
    collected_at: datetime
    static: Optional[StaticInfo] = None
    latest: Optional[LatestSample] = None
    host: Optional[HostMetrics] = None


# --- Auth ---------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    username: str
