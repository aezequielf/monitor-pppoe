from __future__ import annotations

import pytest

from app.monitor.rates import RateTracker


def test_first_sample_only_sets_baseline() -> None:
    tracker = RateTracker()
    assert tracker.update(
        up_bytes=1_000,
        up_ts=10.0,
        down_bytes=2_000,
        down_ts=10.0,
        session_key="sesion-1",
    ) == (None, None)


def test_rate_from_byte_delta() -> None:
    tracker = RateTracker()
    tracker.update(
        up_bytes=0,
        up_ts=10.0,
        down_bytes=0,
        down_ts=10.0,
        session_key="sesion-1",
    )
    up_mbps, down_mbps = tracker.update(
        up_bytes=5_000_000,
        up_ts=15.0,
        down_bytes=10_000_000,
        down_ts=15.0,
        session_key="sesion-1",
    )
    assert up_mbps == pytest.approx(8.0)
    assert down_mbps == pytest.approx(16.0)


def test_zero_delta_is_zero_mbps() -> None:
    tracker = RateTracker()
    tracker.update(
        up_bytes=100,
        up_ts=10.0,
        down_bytes=200,
        down_ts=10.0,
        session_key="sesion-1",
    )
    assert tracker.update(
        up_bytes=100,
        up_ts=15.0,
        down_bytes=200,
        down_ts=15.0,
        session_key="sesion-1",
    ) == (0.0, 0.0)


def test_counter_reset_discards_delta() -> None:
    tracker = RateTracker()
    tracker.update(
        up_bytes=10_000,
        up_ts=10.0,
        down_bytes=20_000,
        down_ts=10.0,
        session_key="sesion-1",
    )
    assert tracker.update(
        up_bytes=100,
        up_ts=15.0,
        down_bytes=200,
        down_ts=15.0,
        session_key="sesion-1",
    ) == (None, None)


def test_session_change_resets_baseline() -> None:
    tracker = RateTracker()
    tracker.update(
        up_bytes=10_000,
        up_ts=10.0,
        down_bytes=20_000,
        down_ts=10.0,
        session_key="sesion-1",
    )
    assert tracker.update(
        up_bytes=20_000,
        up_ts=15.0,
        down_bytes=40_000,
        down_ts=15.0,
        session_key="sesion-2",
    ) == (None, None)


def test_missing_value_keeps_previous_baseline() -> None:
    tracker = RateTracker()
    tracker.update(
        up_bytes=0,
        up_ts=10.0,
        down_bytes=0,
        down_ts=10.0,
        session_key="sesion-1",
    )
    assert tracker.update(
        up_bytes=None,
        up_ts=15.0,
        down_bytes=None,
        down_ts=15.0,
        session_key="sesion-1",
    ) == (None, None)
    up_mbps, down_mbps = tracker.update(
        up_bytes=10_000_000,
        up_ts=20.0,
        down_bytes=20_000_000,
        down_ts=20.0,
        session_key="sesion-1",
    )
    assert up_mbps == pytest.approx(8.0)
    assert down_mbps == pytest.approx(16.0)
