"""Unit tests for capabilities/schedule.py (Phase 3, Milestone 7)."""

import asyncio

import pytest

from capabilities.schedule import BriefScheduler, ScheduleConfig


@pytest.mark.unit
class TestScheduleConfig:
    def test_owner_is_required(self):
        with pytest.raises(ValueError, match="owner"):
            BriefScheduler(ScheduleConfig(owner=""), on_brief=lambda: None)


@pytest.mark.unit
class TestBriefScheduler:
    @pytest.mark.asyncio
    async def test_max_runs_caps_execution_count(self):
        run_count = 0

        async def _on_brief():
            nonlocal run_count
            run_count += 1

        # interval_hours=0 so the loop doesn't actually wait between runs
        # in this test -- max_runs is what should stop it, not the clock.
        scheduler = BriefScheduler(
            ScheduleConfig(owner="test-owner", interval_hours=0, max_runs=3), on_brief=_on_brief
        )
        scheduler.start()
        await asyncio.wait_for(scheduler._task, timeout=5)

        assert run_count == 3

    @pytest.mark.asyncio
    async def test_stop_halts_an_unbounded_scheduler(self):
        run_count = 0

        async def _on_brief():
            nonlocal run_count
            run_count += 1

        scheduler = BriefScheduler(ScheduleConfig(owner="test-owner", interval_hours=0), on_brief=_on_brief)
        scheduler.start()
        await asyncio.sleep(0.05)
        scheduler.stop()
        await asyncio.wait_for(scheduler._task, timeout=5)

        assert run_count >= 1  # ran at least once before being stopped

    @pytest.mark.asyncio
    async def test_a_failing_brief_run_does_not_kill_the_scheduler(self):
        run_count = 0

        async def _on_brief():
            nonlocal run_count
            run_count += 1
            if run_count == 1:
                raise RuntimeError("simulated failure")

        scheduler = BriefScheduler(
            ScheduleConfig(owner="test-owner", interval_hours=0, max_runs=2), on_brief=_on_brief
        )
        scheduler.start()
        await asyncio.wait_for(scheduler._task, timeout=5)

        assert run_count == 2  # the failure on run 1 didn't stop run 2
