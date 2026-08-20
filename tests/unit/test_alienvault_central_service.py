"""Unit tests for services/alienvault_central_service.py's pure helpers.
No live calls -- _time_window_ms is the only pure function in this module
(everything else needs a real HTTP round-trip, covered by this session's
live verification instead, not unit tests)."""

import time

import pytest

from services.alienvault_central_service import _time_window_ms


@pytest.mark.unit
class TestTimeWindowMs:
    def test_default_24h_window_width(self):
        since_ms, now_ms = _time_window_ms(24)
        assert now_ms - since_ms == 24 * 3600 * 1000

    def test_1h_window_width(self):
        since_ms, now_ms = _time_window_ms(1)
        assert now_ms - since_ms == 3600 * 1000

    def test_now_is_close_to_actual_current_time(self):
        _since_ms, now_ms = _time_window_ms(24)
        assert abs(now_ms - int(time.time() * 1000)) < 5000

    def test_30_day_window(self):
        since_ms, now_ms = _time_window_ms(24 * 30)
        assert now_ms - since_ms == 30 * 24 * 3600 * 1000
