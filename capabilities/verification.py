"""Argus <Verifier> capability (explicit user request, 2026-08-05: "in
addition to our compliance agent, we should have a sub agent that
accurately verifies a subagent response against what is actually on the
solution").

Distinct from Themis <Compliance & Debug> (capabilities/synergy.py's
run_themis_sweep): Themis checks whether the agent PIPELINE is healthy --
errors, stuck findings, ungrounded output. Argus checks whether one
SPECIFIC REPORTED NUMBER is actually true right now, by re-running the
same live SentinelOne query fresh and comparing against what was
cached/reported. Built directly in response to a real discrepancy caught
this session: the dashboard reported 53 endpoints while SentinelOne's own
console showed 54 (root-caused and fixed separately in
services/sentinelone_dashboard_service.py -- this capability is the
standing mechanism to catch the *next* one of these before a user does).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    kind: str  # "match" | "mismatch" | "execution_error"
    claim_type: str
    claimed_value: Any = None
    actual_value: Any = None
    note: str = ""


async def verify_endpoint_count(claimed_count: int) -> VerificationResult:
    from services import sentinelone_recipe_executor as executor

    result, err = await executor._call("list_inventory_items", {"limit": 1000, "fetch_fields": "MINIMAL"})
    if err or not isinstance(result, dict):
        return VerificationResult(kind="execution_error", claim_type="endpoint_count", claimed_value=claimed_count, note=err or "no result")
    actual = len(result.get("data", []))
    if actual == claimed_count:
        return VerificationResult(kind="match", claim_type="endpoint_count", claimed_value=claimed_count, actual_value=actual)
    return VerificationResult(
        kind="mismatch", claim_type="endpoint_count", claimed_value=claimed_count, actual_value=actual,
        note=(
            f"Live re-query returned {actual}, reported value was {claimed_count}. Could be legitimate "
            "drift (an endpoint enrolled/decommissioned between the original query and this recheck) or a "
            "real bug in how the original count was computed -- if this keeps recurring for the same field, "
            "escalate to Themis for a process-level check."
        ),
    )


async def verify_group_count(claimed_count: int) -> VerificationResult:
    from services import sentinelone_recipe_executor as executor

    result, err = await executor._call("list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"})
    if err or not isinstance(result, dict):
        return VerificationResult(kind="execution_error", claim_type="group_count", claimed_value=claimed_count, note=err or "no result")
    items = result.get("data", [])
    groups = {i.get("s1GroupName") for i in items if i.get("s1GroupName")}
    actual = len(groups)
    if actual == claimed_count:
        return VerificationResult(kind="match", claim_type="group_count", claimed_value=claimed_count, actual_value=actual)
    return VerificationResult(
        kind="mismatch", claim_type="group_count", claimed_value=claimed_count, actual_value=actual,
        note=(
            f"Live re-query found {actual} groups with an active endpoint right now, reported value was "
            f"{claimed_count}. No dedicated groups-listing tool exists in this integration (confirmed by a "
            "full 33-tool scan), so a group with zero current endpoints is structurally invisible to this "
            "count on either side of the comparison -- a mismatch here usually means endpoint state changed "
            "between queries, not a code defect."
        ),
    )


async def verify_alert_status_count(status: str, claimed_count: int, window_hours: Optional[int] = 24) -> VerificationResult:
    """Re-checks one Alert.status count, honoring the same 24h window the
    dashboard now uses (services/sentinelone_dashboard_service.py) --
    verifying a 24h-scoped claim against an all-time re-query would
    always "mismatch" by construction, so the window must match."""
    import json

    from services import sentinelone_recipe_executor as executor

    filters = [{"fieldId": "status", "filterType": "string_equals", "value": status}]
    if window_hours is not None:
        ts, err = await executor._call("get_timestamp_range", {"hours": window_hours})
        if not err and isinstance(ts, dict) and ts.get("offset_time"):
            start_ms, err2 = await executor._call("iso_to_unix_timestamp", {"iso_datetime": ts["offset_time"]})
            if not err2:
                try:
                    filters.append({"fieldId": "createdAt", "filterType": "datetime_range", "start": int(start_ms)})
                except (TypeError, ValueError):
                    pass

    result, err = await executor._call("search_alerts", {"filters": json.dumps(filters), "first": 1})
    if err or not isinstance(result, dict):
        return VerificationResult(kind="execution_error", claim_type=f"alert_status_{status}", claimed_value=claimed_count, note=err or "no result")
    actual = executor._total_count(result) or 0
    claim_type = f"alert_status_{status}" + (f"_last_{window_hours}h" if window_hours else "_all_time")
    if actual == claimed_count:
        return VerificationResult(kind="match", claim_type=claim_type, claimed_value=claimed_count, actual_value=actual)
    return VerificationResult(
        kind="mismatch", claim_type=claim_type, claimed_value=claimed_count, actual_value=actual,
        note=f"Live re-query returned {actual}, reported value was {claimed_count} (both scoped to the same window).",
    )


async def verify_agents_offline(claimed_count: int) -> VerificationResult:
    """Re-checks agent.consoleConnectivity live against the dashboard's
    cached agents_offline count.

    Added 2026-08-06 specifically because this class of bug -- a reported
    field silently wrong for every endpoint, not just drifted since the
    last query -- is exactly what Argus exists to catch, and this field
    wasn't in its verification scope yet when the real bug happened
    (agent.networkStatus read "connected" almost unconditionally; fixed
    in services/sentinelone_dashboard_service.py and
    services/sentinelone_recipe_executor.py's agent_health recipe, both
    switched to agent.consoleConnectivity). This is the standing
    mechanism to catch the *next* one of these -- e.g. if
    consoleConnectivity itself ever turns out to have the same blind
    spot -- without waiting for a user to notice first."""
    from services import sentinelone_recipe_executor as executor

    result, err = await executor._call("list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"})
    if err or not isinstance(result, dict):
        return VerificationResult(kind="execution_error", claim_type="agents_offline", claimed_value=claimed_count, note=err or "no result")
    items = result.get("data", [])
    actual = sum(1 for i in items if (i.get("agent") or {}).get("consoleConnectivity") is not True)
    if actual == claimed_count:
        return VerificationResult(kind="match", claim_type="agents_offline", claimed_value=claimed_count, actual_value=actual)
    return VerificationResult(
        kind="mismatch", claim_type="agents_offline", claimed_value=claimed_count, actual_value=actual,
        note=(
            f"Live re-query returned {actual}, reported value was {claimed_count}. Connectivity state "
            "changes constantly, so some drift between the cached snapshot and this recheck is expected -- "
            "but if this count comes back suspiciously static across repeated sweeps (e.g. always the same "
            "number, or always 0/near-0 against a large endpoint total), that's the same shape of bug this "
            "check exists to catch, not normal drift -- escalate to Themis for a process-level check."
        ),
    )


async def verify_against_dashboard() -> list[VerificationResult]:
    """Re-checks every key number in the currently-cached dashboard
    snapshot against a fresh live query -- what daemon/scheduler.py's
    periodic argus_sweep task runs. Read-only; never triggers a dashboard
    cache refresh itself, only reads whatever is already cached."""
    from services.sentinelone_dashboard_service import get_cached_snapshot

    snapshot = get_cached_snapshot()
    if snapshot is None or not snapshot.sentinelone_active:
        return []

    results = [
        await verify_endpoint_count(snapshot.endpoint_count),
        await verify_group_count(len(snapshot.groups) - len(snapshot.groups_without_current_endpoint)),
        await verify_alert_status_count("NEW", snapshot.alerts_new, snapshot.alerts_window_hours),
        await verify_agents_offline(snapshot.agents_offline),
    ]
    return results


def format_results(results: list[VerificationResult]) -> str:
    if not results:
        return "Argus <Verifier> here -- nothing cached yet to verify against."
    lines = ["Argus <Verifier> here -- re-checked against a fresh live query:"]
    for r in results:
        if r.kind == "match":
            lines.append(f"- {r.claim_type}: MATCH (claimed {r.claimed_value}, live re-query also {r.actual_value})")
        elif r.kind == "mismatch":
            lines.append(f"- {r.claim_type}: MISMATCH -- claimed {r.claimed_value}, live re-query says {r.actual_value}. {r.note}")
        else:
            lines.append(f"- {r.claim_type}: could not verify ({r.note})")
    return "\n".join(lines)
