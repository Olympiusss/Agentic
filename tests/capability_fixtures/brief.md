# Regression fixture: Resident 24-hour brief (Milestone 7)

Encodes Milestone 7's acceptance bar: *"The brief generates on schedule
from real data, is grounded, and is useful enough to start a shift from.
It reports only; it takes no action."*

## Notification extension (explicit user request, 2026-08-03)

"For every new threat on the env, notify the user via telegram or email."
Treated as an extension of THIS milestone (scheduled/event-driven
reporting), not Objective 2 -- a notification tells a human something
happened; it does not isolate a host, kill a process, or open a ticket.
See `capabilities/notifier.py`'s module docstring for the full reasoning.

## Pass criteria (`tests/unit/test_brief_capability.py`,
`tests/unit/test_notifier.py`, `tests/unit/test_schedule.py`)

1. `run_brief` composes only `incident_status`, `endpoint_count`, and
   `agent_health` through `services.sentinelone_recipe_executor.execute()`
   -- never a raw tool.
2. A failure in any composed recipe short-circuits the brief with
   `execution_error`, never a partial brief presented as complete.
3. `notify_telegram`/`notify_email` gracefully no-op
   (`kind="not_configured"`) when their credentials aren't set, rather
   than raising and breaking the underlying detection work.
4. `BriefScheduler` requires an explicit `owner` at construction and an
   explicit `start()` call -- it never runs on import, and `max_runs`
   genuinely caps execution count.
