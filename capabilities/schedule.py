"""Windowed, capped scheduler for the resident 24-hour brief (Phase 3,
Milestone 7).

Deliberately NOT auto-started -- the brief's own guardrail ("confirm the
owner, format, and delivery channel before enabling it") means this
requires an explicit start() call with real configuration; nothing here
runs on import or by default.

Standalone, capability-level scheduler -- not yet wired into
daemon/scheduler.py's own task-registration mechanism. That's a real,
flagged follow-up (see capabilities/registry.yaml's own notes), not
forgotten -- the daemon is a separate process with its own lifecycle, and
wiring into it is additional integration work beyond this brief's own
acceptance criteria.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    owner: str  # who confirmed/owns this schedule -- required, not defaulted
    interval_hours: int = 24
    max_runs: Optional[int] = None  # None = unbounded (still requires explicit start())


class BriefScheduler:
    """A single, explicitly-started/-stopped scheduled brief run."""

    def __init__(self, config: ScheduleConfig, on_brief: Callable[[], Awaitable[None]]):
        if not config.owner:
            raise ValueError("ScheduleConfig.owner is required -- 'confirm the owner ... before enabling it'")
        self.config = config
        self._on_brief = on_brief
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self.run_count = 0

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            if self.config.max_runs is not None and self.run_count >= self.config.max_runs:
                logger.info(
                    "BriefScheduler (owner=%s) reached max_runs=%s, stopping",
                    self.config.owner, self.config.max_runs,
                )
                return
            try:
                await self._on_brief()
            except Exception as e:  # noqa: BLE001
                logger.error("Scheduled brief run failed: %s", e, exc_info=True)
            self.run_count += 1
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.config.interval_hours * 3600)
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("scheduler already started")
        logger.info(
            "BriefScheduler starting (owner=%s, interval=%sh, max_runs=%s)",
            self.config.owner, self.config.interval_hours, self.config.max_runs,
        )
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._stopped.set()
