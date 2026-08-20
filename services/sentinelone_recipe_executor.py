"""Production executor for the SentinelOne validated recipes.

Phase 2 (Milestones 0-8) built and live-validated the recipes in
`data/knowledge/sentinelone/recipes/`, proven correct by
`tests/sentinelone_coverage_harness.py` against the real tenant (12/12,
see `data/knowledge/sentinelone/coverage_matrix/accuracy_report.md`). That
harness talks to a standalone stdio session (`scripts/_sentinelone_mcp.py`)
and fills recipe inputs with hardcoded test literals -- neither is
appropriate for live chat. This module is a production port: one async
function per `status: stable` recipe, parameterized by entities extracted
from a real user question (`services/sentinelone_entity_extraction.py`),
calling the same MCP path the live chat tool loop already uses
(`services/mcp_client.py`'s `get_mcp_client().call_tool(...)`).

Deliberately *not* a generic "interpret tool_calls + resolve {{x}}
templates" engine -- the recipes' placeholder notation is natural language,
not a strict grammar, and real per-recipe bespoke logic already exists
(e.g. agent_health's client-side networkStatus classification after a
confirmed-real 400 on server-side filtering). Reimplementing that
generically risks reintroducing bugs this phase already found and fixed
once (see the coverage-matrix accuracy report's "tuning applied" section).
A handful of concrete functions, ported from logic already validated
against the live tenant, is the lower-risk choice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from services import sentinelone_entity_extraction as extract
from services import sentinelone_grounding_service as grounding
from services.sentinelone_environment_cache_service import (
    SentinelOneEnvironmentCacheService,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "sentinelone"
REPO_ROOT = Path(__file__).resolve().parent.parent
DV_COOKBOOK_DIR = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "dv_cookbook"

# Calibrated empirically against BOTH sides, same discipline as the
# router-level ROUTER_CONFIDENCE_THRESHOLD (sentinelone_router_service.py):
# real dv_hunt-shaped questions scored 0.57-0.70 against the real cookbook;
# genuinely unrelated text ("tell me a joke", "what is your favorite
# color", nonsense tokens) scored 0.41-0.51 -- an initial, unvalidated
# guess of 0.4 was caught failing exactly because it was never checked
# against the distractor side at all. The retrieval store's chunk text
# (full template descriptions) is denser/longer than the router's short
# example questions, so its noise floor is measurably higher than the
# router's own 0.57-0.61 distractor range -- the two thresholds are not
# interchangeable. 0.54 is the lowest value that cleanly separates every
# tested distractor (max 0.511) from every tested real match (min 0.57).
DV_HUNT_TEMPLATE_CONFIDENCE_FLOOR = 0.54

_MATCH_COUNT_RE = re.compile(r"Match Count:\s*([\d.]+)")
_ISO8601_HOURS_RE = re.compile(r"^PT(\d+)H$")
_ISO8601_DAYS_RE = re.compile(r"^P(\d+)D$")


@dataclass
class RecipeOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    answer: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None
    # Optional structured facts a recipe already fetched, for a capability
    # (Phase 3) to chain into a later step without re-fetching or parsing
    # the formatted answer text -- e.g. threat_detail's storylineId, so
    # Triage can pivot into storyline_pivot for blast-radius evidence. The
    # recipe itself still made the only tool call; this just avoids
    # discarding its structured result. Never used by live chat today.
    raw_data: Optional[dict[str, Any]] = None


def is_sentinelone_active() -> bool:
    """Gates the whole interception feature. Mirrors the live-connection
    check already used to decide MCP tool visibility for the model
    (`claude_service.py`'s `_load_mcp_tools`) -- if the sentinelone server
    isn't actually connected, this is a complete no-op."""
    try:
        from services.mcp_client import get_mcp_client

        mcp_client = get_mcp_client()
        if mcp_client is None:
            return False
        return bool(mcp_client.get_connection_status().get(SERVER_NAME, False))
    except Exception:  # noqa: BLE001
        logger.debug("Could not determine SentinelOne connection status", exc_info=True)
        return False


def _tenant_label() -> str:
    """Real tenant/account name from the environment memory cache (built
    Milestone 6, populated from a live Milestone 1 discovery run, but never
    previously consumed anywhere). Falls back to a generic, non-fabricated
    label rather than hardcoding a specific tenant name in code."""
    try:
        cache = SentinelOneEnvironmentCacheService.get()
        if cache.accounts:
            return next(iter(cache.accounts.values()))
    except Exception:  # noqa: BLE001
        logger.debug("Could not read SentinelOne environment cache", exc_info=True)
    return "the connected SentinelOne tenant"


def _content_text(result: dict[str, Any]) -> Optional[str]:
    for block in result.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text")
    return None


async def _call(tool: str, parameters: dict[str, Any]) -> tuple[Any, Optional[str]]:
    """Call a sentinelone MCP tool via the production client, unwrap and
    JSON-decode its content. Returns (parsed_result, error_text); never
    raises, mirroring `mcp_client.call_tool`'s own never-raise contract."""
    from services.mcp_client import get_mcp_client

    mcp_client = get_mcp_client()
    if mcp_client is None:
        return None, "MCP client is not available"
    result = await mcp_client.call_tool(SERVER_NAME, tool, parameters, timeout=30.0)
    text = _content_text(result)
    if result.get("error"):
        return None, text or "unknown MCP error"
    if text is None:
        return None, "empty tool response"
    try:
        return json.loads(text), None
    except (json.JSONDecodeError, TypeError):
        return text, None


def _edges(payload: Any) -> list[dict[str, Any]]:
    """GraphQL-shaped tools (Alerts/Vulnerabilities/Misconfigurations)."""
    if isinstance(payload, dict):
        return [e.get("node", {}) for e in payload.get("edges", []) if isinstance(e, dict)]
    return []


def _total_count(payload: Any) -> Optional[int]:
    """Alerts uses camelCase `totalCount` -- confirmed distinct from
    Vulnerabilities/Misconfigurations' snake_case `total_count`
    (`data/knowledge/sentinelone/mcp_tools.md`'s "Critical corrections";
    this exact mismatch caused a real 37,863x undercount before it was
    caught in Milestone 7). Do not unify these into one key lookup."""
    if isinstance(payload, dict):
        return payload.get("totalCount")
    return None


def _empty_answer(
    question_class: str, source_module: str, tenant: str, window: str, body: str
) -> str:
    """`body` should already read naturally as "nothing found" on its own
    (e.g. "No endpoints matched..."). Since the grounding line no longer
    displays the classification (`format_grounding_line`'s post-Phase-2
    simplification), a classification that means something *more specific*
    than plain "nothing in this window" -- not licensed, outside retention,
    a scope/permission error -- gets folded into the body as a short clause
    so that information isn't silently lost. The common case
    (NO_MATCHING_ACTIVITY) adds nothing `body` doesn't already say, so it's
    left alone rather than padded with a redundant clause."""
    classification, reason = grounding.classify_empty_result(question_class)
    full_body = body
    if classification != grounding.EmptyResultClassification.NO_MATCHING_ACTIVITY:
        full_body = f"{body} ({reason})"
    return grounding.format_grounded_answer(
        body=full_body,
        source_module=source_module,
        tenant=tenant,
        window=window,
        empty_classification=classification,
        empty_reason=reason,
    )


@lru_cache(maxsize=None)
def _load_dv_hunt_template(template_id: str) -> Optional[dict]:
    path = DV_COOKBOOK_DIR / f"{template_id}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_default_window(duration: Optional[str]) -> tuple[str, int]:
    """ISO 8601 duration -> (get_timestamp_range kwarg, amount). Every
    current template uses PT24H; hours/days are the only forms handled
    since that's all that exists to parse -- falls back to 24 hours for
    anything else rather than failing the whole hunt outright."""
    if duration:
        m = _ISO8601_HOURS_RE.match(duration)
        if m:
            return "hours", int(m.group(1))
        m = _ISO8601_DAYS_RE.match(duration)
        if m:
            return "days", int(m.group(1))
    return "hours", 24


def _parse_powerquery_match_count(text: str) -> Optional[int]:
    """PowerQuery results come back as a text blob ("Match Count: 5.0\\n
    Columns: ...\\nResults:\\nRow 1: [...]"), not clean JSON like the
    GraphQL-backed tools -- pull the count out rather than guess from
    string length/emptiness."""
    m = _MATCH_COUNT_RE.search(text)
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except ValueError:
        return None


def _parse_powerquery_rows(text: str) -> list[dict[str, Any]]:
    """Parses PowerQuery's text-blob rows into column-name-keyed dicts.
    Confirmed live shape (artifact-reputation build, 2026-08-04):
    'Column Names: event.time, endpoint.name, ...\\n\\nResults:\\nRow 1:
    [1784797919058, \\'CYV-CA-LPT-030\\', None, ...]\\nRow 2: [...]'. Each
    row is literally a Python list repr (None/single-quoted
    strings/numbers), not JSON -- ast.literal_eval is the safe, correct
    parser for that, not json.loads."""
    import ast
    import re

    cols_m = re.search(r"Column Names:\s*(.+)", text)
    if not cols_m:
        return []
    columns = [c.strip() for c in cols_m.group(1).split(",")]

    rows: list[dict[str, Any]] = []
    for row_m in re.finditer(r"Row \d+:\s*(\[.*\])", text):
        try:
            values = ast.literal_eval(row_m.group(1))
        except (ValueError, SyntaxError):
            continue
        if isinstance(values, (list, tuple)):
            rows.append(dict(zip(columns, values)))
    return rows


async def _execute_dv_hunt(question: str) -> RecipeOutcome:
    """Two-level match: the router already confirmed this question is
    dv-hunt-shaped (0.62+ against the coverage matrix's dv_hunt examples);
    this picks *which* of the dv_cookbook's templates fits via the same
    embedding retrieval store Milestone 6 already built
    (source="dv_hunt_template"), then runs that template's query directly
    via powerquery() -- never purple_ai(), confirmed permanently
    unavailable. Every answer states the hand-composed, not-Purple-AI-verified
    provenance (confirmed product decision) rather than presenting it as an
    equally-authoritative recipe."""
    question_class = "dv_hunt"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()

    from services.sentinelone_retrieval_store import retrieve as retrieve_chunks

    hits = retrieve_chunks(question, k=1, source_filter=["dv_hunt_template"])
    if not hits or hits[0]["score"] < DV_HUNT_TEMPLATE_CONFIDENCE_FLOOR:
        return RecipeOutcome(
            kind="execution_error",
            error="no dv_hunt template matched this question confidently enough",
        )
    template_id = hits[0]["chunk_key"]
    template = _load_dv_hunt_template(template_id)
    if template is None:
        return RecipeOutcome(
            kind="execution_error", error=f"template '{template_id}' not found on disk"
        )

    query = template.get("query_source", {}).get("resulting_query")
    if not query:
        return RecipeOutcome(
            kind="execution_error", error=f"template '{template_id}' has no resulting_query"
        )

    # Deep Visibility queries are mandatorily windowed (the protocol's own
    # "every DV query carries an explicit time window" rule) -- but unlike
    # threat_count, there's no honest "all time" fallback for a DV hunt to
    # silently default to. A real production question ("find file downloads
    # ending in .zip/.iso/.html", no time range given) exposed that always
    # falling back to the template's default_window meant the agent silently
    # assumed a 24h window instead of asking -- confirmed as unwanted
    # behavior. If the question doesn't state a window, ask rather than
    # assume; the template's own default is offered as a suggestion, not
    # applied unasked.
    explicit_window = extract.extract_time_window(question)
    if explicit_window is None:
        default_kwarg, default_amount = _parse_default_window(template.get("default_window"))
        return RecipeOutcome(
            kind="needs_clarification",
            clarifying_question=(
                f"What time range should I search for the "
                f"'{template.get('hunt_pattern')}' hunt ({template_id})? "
                f"For example, \"last {default_amount} {default_kwarg}\" -- "
                "I don't want to assume a window that might miss what you're after."
            ),
        )
    window_kwarg, window_amount = explicit_window
    ts, err = await _call("get_timestamp_range", {window_kwarg: window_amount})
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    start = ts.get("offset_time") if isinstance(ts, dict) else None
    end = ts.get("current_time") if isinstance(ts, dict) else None
    if not start or not end:
        return RecipeOutcome(
            kind="execution_error", error="get_timestamp_range did not return a usable window"
        )

    result, err = await _call(
        "powerquery", {"query": query, "start_datetime": start, "end_datetime": end}
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    result_text = result if isinstance(result, str) else json.dumps(result)
    match_count = _parse_powerquery_match_count(result_text)

    mitre = template.get("mitre", [])
    mitre_text = "; ".join(
        f"{m.get('technique_id')} ({m.get('technique_name', '')})" for m in mitre
    )
    window_label = f"last {window_amount} {window_kwarg}"
    # Honesty caveat baked into source_module itself (confirmed product
    # decision) rather than a separate structured field, since the
    # grounding line is deliberately Source+Client only now.
    caveated_source = f"{source_module} (hand-composed template, not Purple-AI-verified)"

    if not match_count:
        body = (
            f"No matches for the '{template.get('hunt_pattern')}' hunt ({template_id}) "
            f"in the {window_label}. MITRE: {mitre_text}."
        )
        answer = _empty_answer(question_class, caveated_source, tenant, window_label, body)
    else:
        body = (
            f"Found {match_count} match(es) for the '{template.get('hunt_pattern')}' hunt "
            f"({template_id}) in the {window_label}. MITRE: {mitre_text}.\n\n{result_text[:1500]}"
        )
        answer = grounding.format_grounded_answer(
            body=body,
            source_module=caveated_source,
            tenant=tenant,
            window=window_label,
            result_count=match_count,
        )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_threat_count(question: str) -> RecipeOutcome:
    question_class = "threat_count"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    window = extract.extract_time_window(question)

    if window is None:
        result, err = await _call("search_alerts", {"first": 1})
        if err:
            return RecipeOutcome(kind="execution_error", error=err)
        count = _total_count(result)
        window_label = "all time"
    else:
        kwarg_name, amount = window
        # kwarg_name is exactly get_timestamp_range's own parameter name
        # (hours/days/weeks/months) -- live-confirmed to accept hours=
        # the same way it was already validated for days= (Milestone 4).
        ts, err = await _call("get_timestamp_range", {kwarg_name: amount})
        if err:
            return RecipeOutcome(kind="execution_error", error=err)
        start_iso = ts.get("offset_time") if isinstance(ts, dict) else None
        if not start_iso:
            return RecipeOutcome(
                kind="execution_error",
                error="get_timestamp_range did not return offset_time",
            )
        start_ms_raw, err = await _call("iso_to_unix_timestamp", {"iso_datetime": start_iso})
        if err:
            return RecipeOutcome(kind="execution_error", error=err)
        try:
            start_ms = int(start_ms_raw)
        except (TypeError, ValueError):
            return RecipeOutcome(
                kind="execution_error",
                error=f"iso_to_unix_timestamp returned a non-numeric value: {start_ms_raw!r}",
            )
        windowed, err = await _call(
            "search_alerts",
            {
                "first": 1,
                "filters": json.dumps(
                    [{"fieldId": "createdAt", "filterType": "datetime_range", "start": start_ms}]
                ),
            },
        )
        if err:
            return RecipeOutcome(kind="execution_error", error=err)
        count = _total_count(windowed)
        unit_label = kwarg_name[:-1] if amount == 1 else kwarg_name  # hours -> hour
        window_label = f"last {amount} {unit_label}"

    if count is None:
        return RecipeOutcome(kind="execution_error", error="search_alerts did not return totalCount")

    if count == 0:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            window_label,
            f"No threats are recorded on {tenant} in the {window_label}.",
        )
    else:
        # Body says "threat(s)" to match the user's own vocabulary -- this
        # tenant's MCP server has no distinct "Threats" tool at all (threat
        # questions correctly route to Alerts, confirmed in Milestone 0/1),
        # but the honest, correct system name still surfaces via `Source:
        # SentinelOne Alerts` in the grounding line, not in the prose.
        noun = "threat" if count == 1 else "threats"
        answer = grounding.format_grounded_answer(
            body=f"{tenant} has {count} {noun} in the {window_label}.",
            source_module=source_module,
            tenant=tenant,
            window=window_label,
            result_count=count,
        )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_endpoint_count(question: str) -> RecipeOutcome:
    # No `surface: "ENDPOINT"` filter (removed 2026-08-05) -- confirmed
    # live it routes to a DIFFERENT underlying REST endpoint
    # (/xdr/assets/surface/endpoint vs /xdr/assets) that silently drops
    # one real, active endpoint SentinelOne's own console counts (53 vs
    # the console's 54, verified against a live screenshot). Dropping the
    # filter matches the console exactly; same fix applied to every other
    # list_inventory_items call in this module below.
    question_class = "endpoint_count"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "list_inventory_items", {"limit": 1000, "fetch_fields": "MINIMAL"}
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    items = result.get("data", []) if isinstance(result, dict) else []
    count = len(items)

    if count == 0:
        answer = _empty_answer(
            question_class, source_module, tenant, "all time", "No endpoints were returned."
        )
        return RecipeOutcome(kind="answered", answer=answer)

    # Neither inventory tool reports a total distinct from the returned
    # page (pagination is confirmed always {}) -- if the page came back at
    # exactly the fetch limit, the true count may be higher, so this must
    # be reported as a lower bound, never as a confirmed total.
    if count >= 1000:
        body = f"{tenant} has at least {count} endpoints (page limit reached; the true count may be higher)."
    else:
        body = f"{tenant} has {count} endpoints."
    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=count,
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_group_count(question: str) -> RecipeOutcome:
    # "Groups" here is the org/scope hierarchy concept (s1GroupName on each
    # InventoryItem) -- distinct from SentinelOne's separate "Threat Groups"
    # concept (grouping alerts by hash/family). No dedicated group tool
    # exists (confirmed Milestone 1); groups are only recoverable by
    # fetching endpoint inventory and reading the s1GroupName field each
    # record already carries. See the coverage-matrix row's elicited_by note
    # -- this class exists specifically because "how many groups" was once
    # silently misrouted to endpoint_count.
    question_class = "group_count"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"}
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    items = result.get("data", []) if isinstance(result, dict) else []

    if not items:
        answer = _empty_answer(
            question_class, source_module, tenant, "all time", "No endpoint inventory records were returned."
        )
        return RecipeOutcome(kind="answered", answer=answer)

    endpoint_groups = {i.get("s1GroupName") for i in items if i.get("s1GroupName")}

    # Cross-reference vulnerability records' scope.group -- a group with
    # zero current endpoints in the inventory sample can still surface
    # here if any of its assets carries a vulnerability record (explicit
    # user request, 2026-08-05: recover groups without endpoints where
    # possible, and name them explicitly). One unfiltered sample, not
    # per-severity like the dashboard's fuller version -- this is a
    # live chat-latency path, kept cheap.
    vuln_groups: set[str] = set()
    vuln_result, vuln_err = await _call("search_vulnerabilities", {"filters": json.dumps([]), "first": 100})
    if not vuln_err and isinstance(vuln_result, dict):
        for row in _edges(vuln_result):
            group_name = ((row.get("scope") or {}).get("group") or {}).get("name")
            if group_name:
                vuln_groups.add(group_name)

    groups = sorted(endpoint_groups | vuln_groups)
    recovered = sorted(vuln_groups - endpoint_groups)

    if not groups:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "all time",
            "No group information was found on the endpoint inventory records returned.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    body = f"{tenant} has {len(groups)} group(s): {', '.join(groups)}."
    if recovered:
        body += (
            f" Of these, {len(recovered)} ({', '.join(recovered)}) have no endpoint currently reporting -- "
            "recovered only via a vulnerability record scoped to them."
        )
    body += (
        " (No dedicated groups-listing tool exists in this integration, confirmed by a full scan of all 33 "
        "available tools -- groups are inferred from endpoint inventory plus a vulnerability-scope "
        "cross-check, which still may not be fully exhaustive. If SentinelOne's console reports more groups "
        "than this, the remaining difference is almost certainly groups with neither an active endpoint nor "
        "a vulnerability record, not a data error.)"
    )
    if len(items) >= 1000:
        body += " (Based on the first 1,000 endpoints returned -- there may be additional groups if the environment has more endpoints than this.)"

    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=len(groups),
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_incident_status(question: str) -> RecipeOutcome:
    # "Incidents" is confirmed (Milestone 9 live probe of get_alert_history)
    # to be this tenant's console label for Alert.status, not a distinct
    # entity -- see the Incident ontology entity's citation.
    question_class = "incident_status"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()

    async def _count_for(status: str) -> Optional[int]:
        result, err = await _call(
            "search_alerts",
            {
                "filters": json.dumps(
                    [{"fieldId": "status", "filterType": "string_equals", "value": status}]
                ),
                "first": 1,
            },
        )
        if err or not isinstance(result, dict):
            return None
        return _total_count(result)

    statuses = ["NEW", "IN_PROGRESS", "RESOLVED"]
    counts = await asyncio.gather(*(_count_for(s) for s in statuses))
    if any(c is None for c in counts):
        return RecipeOutcome(
            kind="execution_error",
            error="search_alerts did not return totalCount for one or more status values",
        )

    new_count, in_progress_count, resolved_count = counts
    total = new_count + in_progress_count + resolved_count

    if total == 0:
        answer = _empty_answer(
            question_class, source_module, tenant, "all time", "No alerts were returned in any status."
        )
        return RecipeOutcome(kind="answered", answer=answer)

    body = (
        f"{tenant} has {total} incident(s) by status: {new_count} new, "
        f"{in_progress_count} in progress, {resolved_count} resolved."
    )
    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=total,
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_tenant_structure(question: str) -> RecipeOutcome:
    question_class = "tenant_structure"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"}
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    items = result.get("data", []) if isinstance(result, dict) else []

    if not items:
        answer = _empty_answer(
            question_class, source_module, tenant, "all time", "No endpoint inventory records were returned."
        )
        return RecipeOutcome(kind="answered", answer=answer)

    accounts = sorted({i.get("s1AccountName") for i in items if i.get("s1AccountName")})
    sites = sorted({i.get("s1SiteName") for i in items if i.get("s1SiteName")})

    body = (
        f"{tenant}'s environment has {len(accounts)} account(s) ({', '.join(accounts)}) "
        f"and {len(sites)} site(s) ({', '.join(sites)})."
    )
    if len(items) >= 1000:
        body += (
            " (Based on the first 1,000 endpoints returned -- there may be additional "
            "accounts or sites if the environment has more endpoints than this.)"
        )

    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=len(accounts) + len(sites),
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_application_risk(question: str) -> RecipeOutcome:
    question_class = "application_risk"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()

    async def _sample(severity: str) -> list[dict[str, Any]]:
        result, err = await _call(
            "search_vulnerabilities",
            {
                "filters": json.dumps(
                    [{"fieldId": "severity", "filterType": "string_equals", "value": severity}]
                ),
                "first": 100,
            },
        )
        if err or not isinstance(result, dict):
            return []
        return _edges(result)

    # Concurrent, not sequential -- 4 independent severity samples take
    # roughly one round-trip's latency instead of 4x. A single-severity
    # sample was found badly clustered (100/100 CRITICAL came back as one
    # application from what looks like a bulk same-timestamp detection
    # batch) -- sampling across all 4 severities is what actually surfaces
    # the real distribution.
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    samples = await asyncio.gather(*(_sample(s) for s in severities))
    all_rows = [row for sample in samples for row in sample]

    if not all_rows:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "all time",
            "No vulnerability records were returned across any severity.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    counts: dict[str, int] = {}
    for vuln_row in all_rows:
        software = vuln_row.get("software") or {}
        name = software.get("name") if isinstance(software, dict) else None
        if name:
            counts[name] = counts.get(name, 0) + 1

    if not counts:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "all time",
            "Vulnerability records were returned, but none carried a software name to aggregate by.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[:3]

    async def _exact_count(app_name: str) -> Optional[int]:
        result, err = await _call(
            "search_vulnerabilities",
            {
                "filters": json.dumps(
                    [{"fieldId": "softwareName", "filterType": "string_equals", "value": app_name}]
                ),
                "first": 1,
            },
        )
        if err or not isinstance(result, dict):
            return None
        return result.get("total_count")

    exact_counts = await asyncio.gather(*(_exact_count(name) for name, _ in top))

    parts = []
    for (name, _sample_count), exact in zip(top, exact_counts):
        parts.append(f"{name} ({exact} vulnerabilities)" if exact is not None else name)

    body = (
        f"Across a {len(all_rows)}-record cross-section spanning all severities, "
        f"{len(counts)} distinct application(s) appeared. The most frequently flagged: "
        f"{', '.join(parts)}. This reflects the top applications by sample frequency with "
        "exact totals for those named -- not an exhaustive per-application census of every "
        "application in the environment."
    )

    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=len(all_rows),
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_host_lookup(question: str) -> RecipeOutcome:
    question_class = "host_lookup"
    hostname = extract.extract_hostname_substring(question)
    if not hostname:
        return RecipeOutcome(
            kind="needs_clarification",
            clarifying_question="Which hostname (or part of one) should I look up?",
        )
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "search_inventory_items",
        {
            "filters": json.dumps({"name__contains": [hostname]}),
            "limit": 5,
            "fetch_fields": "MINIMAL",
        },
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    items = result.get("data", []) if isinstance(result, dict) else []
    if not items:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "n/a (point lookup)",
            f'No endpoints matched "{hostname}".',
        )
    else:
        names = ", ".join(i.get("name", "?") for i in items[:5])
        answer = grounding.format_grounded_answer(
            body=f'{len(items)} endpoint(s) matched "{hostname}": {names}.',
            source_module=source_module,
            tenant=tenant,
            window="n/a (point lookup)",
            result_count=len(items),
        )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_storyline_pivot(question: str) -> RecipeOutcome:
    question_class = "storyline_pivot"
    storyline_id = extract.extract_uuid(question)
    if not storyline_id:
        return RecipeOutcome(
            kind="needs_clarification",
            clarifying_question="Which storyline ID should I reconstruct? (a UUID from an alert or threat)",
        )
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "search_alerts",
        {
            "filters": json.dumps(
                [{"fieldId": "storylineId", "filterType": "fulltext", "values": [storyline_id]}]
            ),
            "first": 25,
        },
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    rows = _edges(result)
    if not rows:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "all time",
            f"No alerts found for storyline {storyline_id}.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    answer = grounding.format_grounded_answer(
        body=f"Storyline {storyline_id} has {len(rows)} alert(s) in the chain.",
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=len(rows),
    )
    # Raw chain data for a capability to build a timeline/host list from
    # (Phase 3, Milestone 2: Investigator) -- same rationale as
    # threat_detail's raw_data: the recipe already fetched it, this just
    # avoids discarding the structured result behind the formatted count.
    chain = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "severity": r.get("severity"),
            "classification": r.get("classification"),
            "detected_at": r.get("detectedAt"),
            "asset": r.get("asset"),
        }
        for r in rows
    ]
    return RecipeOutcome(kind="answered", answer=answer, raw_data={"storyline_id": storyline_id, "chain": chain})


async def _execute_agent_health(question: str) -> RecipeOutcome:
    question_class = "agent_health"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "list_inventory_items", {"limit": 100, "fetch_fields": "ALL"}
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    items = result.get("data", []) if isinstance(result, dict) else []

    if not items:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "all time",
            "No endpoint inventory records were returned.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    # Bug fixed 2026-08-06: agent.networkStatus is confirmed NOT server-
    # filterable (real 400, "Unknown field" -- see recipes/agent_health.yaml)
    # so this always fetched broadly and classified client-side, which was
    # right. But the field it classified on was wrong: live-verified this
    # session that agent.networkStatus reads "connected" almost
    # unconditionally -- a real endpoint confirmed stale for 3 actual days
    # (via its own lastActiveDt) still reported networkStatus="connected".
    # Milestone 8's "validated" confidence in this field (recipes/
    # agent_health.yaml's own edge-case notes) was built on exactly that
    # blind spot: it sampled 50/50 endpoints, saw networkStatus="connected"
    # on all of them, and concluded "this tenant has zero offline agents"
    # rather than "this field doesn't track real state." agent.
    # consoleConnectivity is the field that actually varies with live state
    # (confirmed: false for the same stale endpoint, and for several
    # others, while networkStatus stayed "connected" on all of them) --
    # same fix already applied to services/sentinelone_dashboard_service.py's
    # agents_offline count.
    connectivity = extract.extract_connectivity_filter(question)
    if connectivity in ("connected", "disconnected"):
        want_connected = connectivity == "connected"
        matched = [
            i
            for i in items
            if ((i.get("agent") or {}).get("consoleConnectivity") is True) == want_connected
        ]
        label = connectivity
    else:
        # Default framing ("which agents are offline"/general health):
        # fetch broadly and classify client-side rather than proxying via
        # assetStatus, which is a different (lifecycle) axis, not
        # connectivity.
        matched = [i for i in items if (i.get("agent") or {}).get("consoleConnectivity") is not True]
        label = "not connected"

    answer = grounding.format_grounded_answer(
        body=f"{len(matched)} of {len(items)} endpoint(s) are {label} (agent.consoleConnectivity).",
        source_module=source_module,
        tenant=tenant,
        window="all time",
        result_count=len(matched),
    )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_cve_traversal(question: str) -> RecipeOutcome:
    question_class = "cve_traversal"
    cve_id = extract.extract_cve_id(question)
    if not cve_id:
        return RecipeOutcome(
            kind="needs_clarification",
            clarifying_question="Which CVE ID should I check? (e.g. CVE-2024-12345)",
        )
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    result, err = await _call(
        "search_vulnerabilities",
        {"filters": json.dumps([{"fieldId": "cveId", "filterType": "string_equals", "value": cve_id}])},
    )
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    rows = _edges(result)
    if not rows:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "n/a (point lookup)",
            f"{cve_id} was not found affecting any asset in this tenant.",
        )
    else:
        answer = grounding.format_grounded_answer(
            body=f"{cve_id} affects {len(rows)} asset(s).",
            source_module=source_module,
            tenant=tenant,
            window="n/a (point lookup)",
            result_count=len(rows),
        )
    return RecipeOutcome(kind="answered", answer=answer)


async def _execute_threat_detail(question: str) -> RecipeOutcome:
    question_class = "threat_detail"
    alert_id = extract.extract_uuid(question)
    if not alert_id:
        return RecipeOutcome(
            kind="needs_clarification",
            clarifying_question="Which alert ID should I pull detail for? (a UUID)",
        )
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    detail, err = await _call("get_alert", {"alert_id": alert_id})
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    if not isinstance(detail, dict) or "severity" not in detail:
        answer = _empty_answer(
            question_class,
            source_module,
            tenant,
            "n/a (point lookup)",
            f"No alert found with ID {alert_id}.",
        )
        return RecipeOutcome(kind="answered", answer=answer)

    severity = grounding.decode_enum_value("Alert", "alert_severity", detail.get("severity"))
    status = grounding.decode_enum_value("Alert", "alert_status", detail.get("status"))
    body = f"Alert {alert_id}: severity={severity}, status={status}."

    # Milestone 9 enrichment: get_alert_history resolves two tenant-hierarchy
    # branches for this same alert -- Response Actions (MITIGATION_ACTION/
    # MITIGATION_RESULT: quarantine/kill, success/fail, which endpoint agent
    # performed it) and per-alert admin attribution (STATUS/ANALYST_VERDICT/
    # NOTES: who changed what). Never fails the whole answer if history is
    # unavailable -- the base alert detail above is already complete on its
    # own. Capped at 5 events per bucket so one heavily-annotated alert
    # can't produce a runaway-length answer.
    history, hist_err = await _call("get_alert_history", {"alert_id": alert_id})
    mitigation_actions: list[str] = []
    if not hist_err and isinstance(history, dict):
        events = _edges(history)
        actions = [e for e in events if e.get("eventType") in ("MITIGATION_ACTION", "MITIGATION_RESULT")]
        admin_events = [e for e in events if e.get("eventType") in ("STATUS", "ANALYST_VERDICT", "NOTES")]
        mitigation_actions = [e.get("eventText", "") for e in actions if e.get("eventText")]
        if actions:
            action_text = "; ".join(e.get("eventText", "") for e in actions[:5] if e.get("eventText"))
            if action_text:
                body += f" Response actions taken: {action_text}"
        if admin_events:
            admin_text = "; ".join(e.get("eventText", "") for e in admin_events[:5] if e.get("eventText"))
            if admin_text:
                body += f" Analyst activity: {admin_text}"

    answer = grounding.format_grounded_answer(
        body=body,
        source_module=source_module,
        tenant=tenant,
        window="n/a (point lookup)",
        result_count=1,
    )
    # Raw facts for a capability to chain on (Phase 3, Milestone 1: Triage
    # pivots storylineId into storyline_pivot for blast-radius evidence
    # without re-fetching or regex-parsing the formatted answer text).
    raw_data = {
        "alert_id": alert_id,
        "storyline_id": detail.get("storylineId"),
        "severity": detail.get("severity"),
        "status": detail.get("status"),
        "analyst_verdict": detail.get("analystVerdict"),
        "classification": detail.get("classification"),
        "asset": detail.get("asset"),
        "mitigation_actions": mitigation_actions,
    }
    return RecipeOutcome(kind="answered", answer=answer, raw_data=raw_data)


async def _execute_vulnerability_general(question: str) -> RecipeOutcome:
    question_class = "vulnerability_general"
    source_module = grounding.resolve_source_module(question_class)
    tenant = _tenant_label()
    severity = extract.extract_severity(question)
    filters = (
        [{"fieldId": "severity", "filterType": "string_equals", "value": severity}] if severity else []
    )
    result, err = await _call("search_vulnerabilities", {"filters": json.dumps(filters), "first": 25})
    if err:
        return RecipeOutcome(kind="execution_error", error=err)
    # Vulnerabilities uses snake_case `total_count`, unlike Alerts'
    # camelCase `totalCount` -- see `_total_count`'s docstring.
    total = result.get("total_count") if isinstance(result, dict) else None
    if total is None:
        return RecipeOutcome(
            kind="execution_error", error="search_vulnerabilities did not return total_count"
        )
    label = f"{severity.lower()} " if severity else ""
    if total == 0:
        answer = _empty_answer(
            question_class, source_module, tenant, "all time", f"No {label}vulnerabilities on record."
        )
    else:
        answer = grounding.format_grounded_answer(
            body=f"{total} {label}vulnerabilities on record.",
            source_module=source_module,
            tenant=tenant,
            window="all time",
            result_count=total,
        )
    return RecipeOutcome(kind="answered", answer=answer)


_EXECUTORS: dict[str, Callable[[str], Any]] = {
    "threat_count": _execute_threat_count,
    "endpoint_count": _execute_endpoint_count,
    "group_count": _execute_group_count,
    "incident_status": _execute_incident_status,
    "tenant_structure": _execute_tenant_structure,
    "application_risk": _execute_application_risk,
    "dv_hunt": _execute_dv_hunt,
    "host_lookup": _execute_host_lookup,
    "storyline_pivot": _execute_storyline_pivot,
    "agent_health": _execute_agent_health,
    "cve_traversal": _execute_cve_traversal,
    "threat_detail": _execute_threat_detail,
    "vulnerability_general": _execute_vulnerability_general,
}


async def execute(question_class: str, question: str) -> RecipeOutcome:
    """Dispatch to the production executor for a router-matched
    question_class. Never raises -- an unexpected exception becomes an
    `execution_error` outcome so the caller can fall through to normal
    model behavior rather than crashing the chat turn."""
    executor = _EXECUTORS.get(question_class)
    if executor is None:
        return RecipeOutcome(
            kind="execution_error", error=f"no production executor wired for '{question_class}'"
        )
    try:
        return await executor(question)
    except Exception as e:  # noqa: BLE001
        logger.error(
            "SentinelOne recipe executor for '%s' raised: %s", question_class, e, exc_info=True
        )
        return RecipeOutcome(kind="execution_error", error=str(e))
