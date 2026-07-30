#!/usr/bin/env python3
"""Read-only SentinelOne environment discovery runner (Phase 2, Milestone 1).

Drives the ten steps in ``data/agent/discovery/environmental_understanding_task.md``
against the connected tenant's ``sentinelone`` MCP server (``purple-mcp``) and
writes ``data/knowledge/sentinelone/environment_map.yaml``.

This is a deterministic script, not an LLM-agentic loop: every step is a
small, bounded set of real tool calls, logged as it happens, so every fact
in the resulting map traces back to exactly what produced it (the
discovery task's rules 1/2). No model judgment is needed for retrieval +
aggregation, so no ANTHROPIC_API_KEY/cost is required here.

Deep Visibility profiling (step 8) is the one step every companion
document singles out as needing confirmation before running -- it is
gated behind ``--confirm-dv`` and skipped (recorded as pending) otherwise.

Run from the repo root::

    python scripts/discover_sentinelone_environment.py                # steps 1-7, 9-10
    python scripts/discover_sentinelone_environment.py --confirm-dv   # also runs step 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

import os  # noqa: E402

import yaml  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

PURPLE_MCP_VERSION = "v0.7.0"
PURPLE_MCP_ARGS = [
    "--from",
    f"git+https://github.com/Sentinel-One/purple-mcp.git@{PURPLE_MCP_VERSION}",
    "purple-mcp",
    "--mode",
    "stdio",
]

# Small, bounded page sizes throughout -- this is exploration, not bulk
# export. See "smallest defensible query first" in
# Sentry_Agent_Task_Execution.md section 1.
SAMPLE_SIZE = 5

OUTPUT_PATH = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "environment_map.yaml"

CORE_DV_EVENT_TYPES = [
    "process",
    "network",
    "dns",
    "file",
    "registry",
    "login",
]


def _server_params() -> StdioServerParameters:
    token = os.environ.get("SENTINELONE_API_TOKEN")
    url = os.environ.get("SENTINELONE_CONSOLE_URL")
    if not token or not url:
        raise RuntimeError(
            "SENTINELONE_API_TOKEN and SENTINELONE_CONSOLE_URL must be set "
            "(in .env or the environment) to run discovery."
        )
    env = os.environ.copy()
    env["PURPLEMCP_CONSOLE_TOKEN"] = token
    env["PURPLEMCP_CONSOLE_BASE_URL"] = url
    return StdioServerParameters(command="uvx", args=PURPLE_MCP_ARGS, env=env)


class ToolLog:
    """Every tool call made during this run, so each fact in the environment
    map can be traced back to exactly what produced it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, tool: str, parameters: dict[str, Any], purpose: str) -> None:
        self.calls.append({"tool": tool, "parameters": parameters, "purpose": purpose})

    def bindings_for(self, *tools: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["tool"] in tools]


async def _call(
    session: ClientSession, log: ToolLog, tool: str, parameters: dict[str, Any], purpose: str
) -> Any:
    result = await session.call_tool(tool, parameters)
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    log.record(tool, parameters, purpose)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _edges(payload: Any) -> list[dict[str, Any]]:
    """GraphQL-shaped tools (alerts/vulnerabilities/misconfigurations) return
    {"edges": [{"node": {...}}], "pageInfo": {...}, "totalCount": N}."""
    if isinstance(payload, dict):
        return [e.get("node", {}) for e in payload.get("edges", []) if isinstance(e, dict)]
    return []


def _total_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        return payload.get("totalCount")
    return None


async def step2_endpoints(session: ClientSession, log: ToolLog) -> tuple[dict[str, Any], list[dict]]:
    """Step 2: endpoint estate. list_inventory_items(surface=ENDPOINT,
    fetch_fields=ALL) on a small sample; record which fields actually
    populate vs. come back empty/absent. Returns the raw items too, since
    they also carry the s1Account/s1Site/s1Group hierarchy fields step 1
    needs -- no reason to fetch endpoints twice."""
    payload = await _call(
        session,
        log,
        "list_inventory_items",
        {"limit": SAMPLE_SIZE, "surface": "ENDPOINT", "fetch_fields": "ALL"},
        "sample endpoint inventory items with all fields to determine real attribute population",
    )
    items = payload.get("data", []) if isinstance(payload, dict) else []
    populated: set[str] = set()
    os_counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if v not in (None, "", [], {}):
                populated.add(k)
        os_name = item.get("resourceType") or item.get("category") or "unknown"
        os_counts[os_name] = os_counts.get(os_name, 0) + 1
    return {
        "sample_size": len(items),
        "populated_attributes": sorted(populated),
        "counts_by_resource_type_in_sample": os_counts,
        "note": (
            "Counts are over this small discovery sample only, not a full "
            "tenant census -- re-run with a larger limit for real totals "
            "once this shape is validated."
        ),
    }, items


async def step1_hierarchy(
    session: ClientSession, log: ToolLog, endpoint_items: list[dict]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Step 1: account/sites/groups. No dedicated hierarchy tool exists in
    this MCP server (confirmed absent from the 33-tool inventory in
    data/knowledge/sentinelone/mcp_tools.md). Two independent recovery
    paths, cross-referenced: (a) each endpoint inventory item's own
    s1AccountId/s1SiteId/s1GroupId/s1ScopePath fields (the more direct
    source -- these are on the entity itself, not inferred), and (b) the
    `scope` sub-object that list_vulnerabilities/list_misconfigurations
    nest (list_alerts does not nest scope at all). Returns (identity,
    hierarchy): identity is the flat entity registry (§tenant.identity in
    the discovery task's template); hierarchy is the parent-child nesting
    (§hierarchy in the template), derived from s1ScopePath.
    """
    identity: dict[str, Any] = {
        "tool_availability": "no dedicated account/site/group tool in this MCP server",
        "accounts": {},
        "sites": {},
        "groups": {},
        "recovered_from": [],
    }
    scope_paths: set[str] = set()

    for item in endpoint_items:
        if not isinstance(item, dict):
            continue
        aid, aname = item.get("s1AccountId"), item.get("s1AccountName")
        sid, sname = item.get("s1SiteId"), item.get("s1SiteName")
        gid, gname = item.get("s1GroupId"), item.get("s1GroupName")
        if aid:
            identity["accounts"][aid] = aname
        if sid:
            identity["sites"][sid] = sname
        if gid:
            identity["groups"][gid] = gname
        if item.get("s1ScopePath"):
            scope_paths.add(item["s1ScopePath"])
    if identity["accounts"] or identity["sites"] or identity["groups"]:
        identity["recovered_from"].append("list_inventory_items (s1AccountId/s1SiteId/s1GroupId fields)")

    for tool, purpose in (
        ("list_vulnerabilities", "cross-check scope sub-object for hierarchy recovery"),
        ("list_misconfigurations", "cross-check scope sub-object for hierarchy recovery"),
    ):
        payload = await _call(
            session,
            log,
            tool,
            {"first": SAMPLE_SIZE, "fields": json.dumps(["id", "scope"])},
            purpose,
        )
        nodes = _edges(payload)
        found_any = False
        for node in nodes:
            scope = node.get("scope") if isinstance(node, dict) else None
            if not scope:
                continue
            found_any = True
            for level, bucket in (("account", "accounts"), ("site", "sites"), ("group", "groups")):
                item = scope.get(level)
                if item and item.get("id"):
                    identity[bucket].setdefault(item["id"], item.get("name"))
        if found_any:
            identity["recovered_from"].append(tool)

    if not identity["recovered_from"]:
        identity["tool_availability"] += (
            "; s1AccountId/s1SiteId/s1GroupId fields and the scope sub-object "
            "on list_vulnerabilities/list_misconfigurations all came back "
            "empty/absent -- hierarchy is not recoverable from this tool "
            "surface with the data currently in this tenant"
        )

    hierarchy: dict[str, Any] = {
        "derived_from": "s1ScopePath field on endpoint inventory items" if scope_paths else None,
        "scope_paths_observed": sorted(scope_paths),
        "note": (
            "s1ScopePath encodes the account->site->group nesting as a path "
            "string per SentinelOne's own convention; parsing it into a "
            "structured tree is left to Milestone 2 (ontology) once more "
            "samples confirm the path format consistently"
            if scope_paths
            else "no s1ScopePath values observed in this sample -- nesting not recoverable"
        ),
    }
    return identity, hierarchy


async def step3_policies(session: ClientSession, log: ToolLog) -> dict[str, Any]:
    """Step 3: endpoint-protection policies. No tool in this MCP server's
    33-tool inventory manages/reads SentinelOne endpoint protection
    policies (list_misconfigurations' policyId/policyGroup fields are
    about CSPM/IaC misconfiguration-detection policies, a different
    concept). Recorded as an honest finding, per the discovery task's rule
    4 ("empty and unlicensed are findings, not gaps")."""
    return {
        "state": "no tool binding available in the sentinelone MCP server",
        "note": (
            "misconfiguration policyId/policyGroup fields exist but refer to "
            "CSPM/IaC detection policies, not SentinelOne endpoint-protection "
            "policies -- not a substitute for this step"
        ),
    }


async def step4_threats_storylines(session: ClientSession, log: ToolLog) -> tuple[dict, dict]:
    """Step 4: threats + storylines. No distinct "Threats" tool exists in
    this MCP server -- routes to the Alerts tool surface (confirmed in
    Milestone 0). The source must be named explicitly, per rule 5."""
    count_payload = await _call(
        session,
        log,
        "search_alerts",
        {"first": 1},
        "count-only query per search_alerts's own documented 'how many' pattern",
    )
    total = _total_count(count_payload)

    sample_payload = await _call(
        session,
        log,
        "list_alerts",
        {"first": SAMPLE_SIZE},
        "sample alerts for schema/lifecycle/storyline detail",
    )
    nodes = _edges(sample_payload)
    severities: set[str] = set()
    statuses: set[str] = set()
    verdicts: set[str] = set()
    classifications: set[str] = set()
    storyline_ids: list[str] = []
    fields_seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        fields_seen.update(node.keys())
        if node.get("severity"):
            severities.add(node["severity"])
        if node.get("status"):
            statuses.add(node["status"])
        if node.get("analystVerdict"):
            verdicts.add(node["analystVerdict"])
        if node.get("classification"):
            classifications.add(node["classification"])
        if node.get("storylineId"):
            storyline_ids.append(node["storylineId"])

    threats = {
        "source": (
            "SentinelOne Alerts (search_alerts/list_alerts) -- no distinct "
            "Threats tool exists in this MCP server; confirmed in Milestone 0"
        ),
        "current_count": total,
        "schema_fields_observed": sorted(fields_seen),
        "lifecycle_states_observed": sorted(statuses),
        "severities_observed": sorted(severities),
        "analyst_verdicts_observed": sorted(verdicts),
        "classifications_observed": sorted(classifications),
    }
    storylines = {
        "structure": (
            "each alert node carries a storylineId field; pivoting means "
            "filtering search_alerts on that storylineId (fulltext filter "
            "type) across the tenant, per the Task Execution Protocol's "
            "storyline pivot procedure"
        ),
        "sample_storyline_ids": storyline_ids,
    }
    return threats, storylines


async def step5_alerts_incidents(session: ClientSession, log: ToolLog) -> dict[str, Any]:
    """Step 5: alerts/incidents. This server has no separate 'incidents'
    concept distinct from Alerts -- recorded as such rather than assumed."""
    payload = await _call(
        session,
        log,
        "list_alerts",
        {"first": SAMPLE_SIZE, "view_type": "ALL"},
        "sample alert types/names present in this tenant",
    )
    nodes = _edges(payload)
    names = sorted({n.get("name") for n in nodes if isinstance(n, dict) and n.get("name")})
    return {"alert_types_observed": names}


async def step6_vulnerabilities_applications(session: ClientSession, log: ToolLog) -> dict[str, Any]:
    """Step 6: vulnerabilities/applications."""
    count_payload = await _call(
        session, log, "search_vulnerabilities", {"first": 1}, "count-only vulnerability query"
    )
    sample_payload = await _call(
        session,
        log,
        "list_vulnerabilities",
        {"first": SAMPLE_SIZE},
        "sample vulnerabilities for schema/severity",
    )
    nodes = _edges(sample_payload)
    fields_seen: set[str] = set()
    severities: set[str] = set()
    for node in nodes:
        if isinstance(node, dict):
            fields_seen.update(node.keys())
            if node.get("severity"):
                severities.add(node["severity"])
    # licensed_or_enabled is derived from whether the sample call actually
    # returned real records, not from whether the count-only call's
    # totalCount field happened to be populated -- the two aren't the same
    # signal, and totalCount coming back empty/absent on a first=1 query
    # does not mean the module is unlicensed if the sample call above
    # returned real data.
    total = _total_count(count_payload)
    return {
        "licensed_or_enabled": bool(nodes),
        "current_count": total if total is not None else "unavailable (totalCount not returned by search_vulnerabilities)",
        "schema_fields_observed": sorted(fields_seen),
        "severities_observed": sorted(severities),
    }


async def step7_optional_modules(session: ClientSession, log: ToolLog) -> dict[str, Any]:
    """Step 7: identity / cloud / asset-discovery. Probed via
    list_inventory_items(surface=...) since those are the closest
    tool-level distinction this MCP server exposes for these modules."""
    modules: dict[str, Any] = {}
    for surface_name, key in (("IDENTITY", "identity"), ("CLOUD", "cloud"), ("NETWORK_DISCOVERY", "asset_discovery")):
        payload = await _call(
            session,
            log,
            "list_inventory_items",
            {"limit": SAMPLE_SIZE, "surface": surface_name, "fetch_fields": "MINIMAL"},
            f"probe {surface_name} surface for licensed/enabled state",
        )
        items = payload.get("data", []) if isinstance(payload, dict) else []
        modules[key] = {
            "licensed_or_enabled": bool(items),
            "sample_count": len(items),
        }
    return modules


async def step8_deep_visibility(session: ClientSession, log: ToolLog) -> dict[str, Any]:
    """Step 8: Deep Visibility profile. One small, capped, windowed
    powerquery per core event type. Query strings here are hand-composed
    with `event.category = "..."` (confirmed valid syntax in Phase 1
    verification) rather than generated via purple_ai(), specifically
    because this step's job is to PROBE which event.category values return
    data at all -- purple_ai() needs a natural-language intent to generate
    from, which doesn't fit a bare validity probe. Once real hunts are
    built (Milestone 5), purple_ai()-generated queries are the documented
    path, per mcp_tools.md."""
    ts = await _call(
        session, log, "get_timestamp_range", {"hours": 24}, "compute a 24h probe window"
    )
    start = ts.get("offset_time") if isinstance(ts, dict) else None
    end = ts.get("current_time") if isinstance(ts, dict) else None

    profile: dict[str, Any] = {
        "surface": "PowerQuery (confirmed in Phase 1; legacy Deep Visibility / S1QL 1.0 not used)",
        "retention": "not independently confirmed in this pass -- would require a query near the retention boundary, which is an expensive/broad query and out of scope for this capped probe",
        "window_used_for_probes": {"start": start, "end": end},
        "event_types": {},
    }
    for event_type in CORE_DV_EVENT_TYPES:
        query = f'event.category = "{event_type}" | limit 1'
        try:
            result = await _call(
                session,
                log,
                "powerquery",
                {"query": query, "start_datetime": start, "end_datetime": end},
                f"probe whether event.category=\"{event_type}\" is valid and returns data in this tenant",
            )
            profile["event_types"][event_type] = {"valid": True, "sample_result": str(result)[:500]}
        except Exception as e:  # noqa: BLE001 -- a bad category can close the whole MCP
            # connection (observed in Phase 1); record and move on rather
            # than let one bad probe abort the rest of discovery.
            profile["event_types"][event_type] = {"valid": False, "error": str(e)}
            raise  # re-raise: a closed connection means no further calls will work this session
    return profile


async def step9_enums(threats: dict, vulns: dict) -> dict[str, Any]:
    """Step 9: enum compilation -- purely from what steps 1-8 actually
    observed, not the full documented range."""
    return {
        "alert_severity": threats.get("severities_observed", []),
        "alert_status": threats.get("lifecycle_states_observed", []),
        "alert_analyst_verdict": threats.get("analyst_verdicts_observed", []),
        "alert_classification": threats.get("classifications_observed", []),
        "vulnerability_severity": vulns.get("severities_observed", []),
    }


async def run(confirm_dv: bool) -> dict[str, Any]:
    log = ToolLog()
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            endpoints, endpoint_items = await step2_endpoints(session, log)
            identity, hierarchy = await step1_hierarchy(session, log, endpoint_items)
            policies = await step3_policies(session, log)
            threats, storylines = await step4_threats_storylines(session, log)
            alerts_incidents = await step5_alerts_incidents(session, log)
            vulns = await step6_vulnerabilities_applications(session, log)
            optional_modules = await step7_optional_modules(session, log)

            if confirm_dv:
                deep_visibility = await step8_deep_visibility(session, log)
            else:
                deep_visibility = {
                    "state": "pending confirmation, not run",
                    "note": (
                        "Deep Visibility profiling is the one step every "
                        "companion document singles out as needing explicit "
                        "confirmation before running. Re-run with --confirm-dv "
                        "once approved."
                    ),
                }

            enums = await step9_enums(threats, vulns)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purple_mcp_version": PURPLE_MCP_VERSION,
        "tenant": {"identity": identity},
        "hierarchy": hierarchy,
        "endpoints": endpoints,
        "policies": policies,
        "threats": threats,
        "storylines": storylines,
        "alerts": alerts_incidents,
        "incidents": (
            "no distinct 'incidents' entity/tool exists in this MCP server -- "
            "Alerts is the only grouping concept observed"
        ),
        "vulnerabilities": vulns,
        "applications": {
            "note": "no dedicated 'applications' tool distinct from vulnerabilities/inventory observed"
        },
        "identity": optional_modules.get("identity"),
        "cloud": optional_modules.get("cloud"),
        "asset_discovery": optional_modules.get("asset_discovery"),
        "deep_visibility": deep_visibility,
        "enums": enums,
        "tool_bindings": log.calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-dv",
        action="store_true",
        help=(
            "Also run step 8 (Deep Visibility profiling). Every companion "
            "document calls this out by name as needing explicit "
            "confirmation before running -- do not pass this flag without "
            "having actually gotten that confirmation."
        ),
    )
    args = parser.parse_args()

    environment_map = asyncio.run(run(confirm_dv=args.confirm_dv))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(environment_map, f, sort_keys=False, allow_unicode=True, width=100)

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Total tool calls made: {len(environment_map['tool_bindings'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
