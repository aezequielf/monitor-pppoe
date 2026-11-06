"""Cálculo de Mbps a partir de contadores acumulados de bytes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class _Counter:
    value: int
    ts: float


@dataclass
class RateTracker:
    """Guarda la muestra anterior de cada dirección y calcula su tasa."""

    session_key: Optional[str] = None
    up: Optional[_Counter] = None
    down: Optional[_Counter] = None

    def reset(self) -> None:
        self.up = None
        self.down = None

    def update(
        self,
        *,
        up_bytes: Optional[int],
        up_ts: Optional[float],
        down_bytes: Optional[int],
        down_ts: Optional[float],
        session_key: Optional[str],
    ) -> tuple[Optional[float], Optional[float]]:
        if session_key != self.session_key:
            self.reset()
            self.session_key = session_key
        return (
            self._rate("up", up_bytes, up_ts),
            self._rate("down", down_bytes, down_ts),
        )

    def _rate(
        self, direction: str, value: Optional[int], ts: Optional[float]
    ) -> Optional[float]:
        if value is None or ts is None:
            return None
        previous: Optional[_Counter] = getattr(self, direction)
        if previous is None or value < previous.value:
            setattr(self, direction, _Counter(value, ts))
            return None

        elapsed = ts - previous.ts
        setattr(self, direction, _Counter(value, ts))
        if elapsed <= 0:
            return None
        return (value - previous.value) * 8 / elapsed / 1_000_000
