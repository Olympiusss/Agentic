"""Real-time SentinelOne environment snapshot for the dashboard.

Structured data for charts, not the natural-language sentences the chat
recipes produce. Refreshed on a background interval (see
start_background_refresh, called once at backend startup) so a dashboard
page load always reads an already-warm cache instead of blocking on a live
SentinelOne round-trip -- the same latency discipline established for the
chat path earlier this project.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 300  # 5 minutes


@dataclass
class ApplicationRisk:
    name: str
    count: int


@dataclass
class DashboardSnapshot:
    generated_at: str
    tenant: str
    sentinelone_active: bool
    endpoint_count: int = 0
    endpoint_count_is_lower_bound: bool = False
    groups: list[str] = field(default_factory=list)
    # Groups are inferred from endpoints that currently carry a group
    # assignment (s1GroupName) -- no dedicated groups-listing tool exists
    # in this integration (confirmed by a full scan of all 33 available
    # tools). A group with zero endpoints reporting right now is
    # invisible to this list, so `groups` may undercount vs. SentinelOne's
    # own console (confirmed live, 2026-08-05: console showed 14 groups,
    # this integration could only recover 12 -- the other 2 have no
    # currently-active endpoints). Always True; kept as an explicit field
    # (not just a docstring) so the frontend can render the caveat.
    groups_may_be_incomplete: bool = True
    # Groups recovered ONLY via a vulnerability record's scope.group (no
    # endpoint in the inventory sample currently carries this group) --
    # named explicitly, not just folded silently into `groups`, per
    # explicit user request 2026-08-05 ("include for groups without
    # endpoint as well, and specify it"). Still may not be exhaustive --
    # no dedicated groups-listing tool exists -- but this recovers more
    # than the endpoint-only view could.
    groups_without_current_endpoint: list[str] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    # Named alerts_*, not incidents_* -- these are Alert.status counts
    # (search_alerts filtered by status). SentinelOne's console has a
    # genuinely separate "Incidents" concept (grouped/correlated alerts,
    # visible in its own UI) that this purple-mcp integration has zero
    # API access to -- confirmed absent from the full 33-tool inventory,
    # same documented ceiling as Policies/Administrators/Forensics
    # (Milestone 9). Labeling raw alert-status counts as "incidents" was
    # a real, misleading bug (caught 2026-08-04): the numbers shown here
    # will never match SentinelOne's own Incidents view, because they're
    # not counting the same thing.
    # Scoped to the last 24h (explicit user request, 2026-08-05: these
    # didn't match "our 24hr context window" -- was an ever-growing
    # all-time cumulative total, not "what's currently active").
    alerts_new: int = 0
    alerts_in_progress: int = 0
    alerts_resolved: int = 0
    alerts_window_hours: int = 24
    vulnerabilities_critical: int = 0
    vulnerabilities_high: int = 0
    vulnerabilities_medium: int = 0
    vulnerabilities_low: int = 0
    # Vulnerabilities are a standing risk total by nature (unlike alerts,
    # they don't "resolve" on their own) -- this is a SECOND, additive
    # figure alongside the all-time critical count above, not a
    # replacement, so patch-priority planning still sees the full total.
    vulnerabilities_critical_new_24h: int = 0
    # `vulnerabilities_critical` is a raw (endpoint x CVE) row count, not a
    # distinct-vulnerability or distinct-application count -- confirmed
    # live (2026-08-05) it can look wildly inflated next to SentinelOne's
    # own per-endpoint Application Vulnerability view, which shows
    # distinct installed apps for ONE machine. Surfacing the single
    # dominant application (usually one outdated, fleet-wide package)
    # turns the raw total into an actionable "patch this one thing"
    # insight instead of an unexplained scary number.
    vulnerabilities_critical_top_driver: Optional[dict] = None
    agents_offline: int = 0
    top_applications: list[ApplicationRisk] = field(default_factory=list)
    # Threat Landscape section (classification/infection breakdown).
    endpoints_infected: int = 0
    endpoints_healthy: int = 0
    threats_malware: int = 0
    threats_ransomware: int = 0
    threats_manual: int = 0
    detection_sources: list[ApplicationRisk] = field(default_factory=list)
    detection_sources_is_sample: bool = True
    error: Optional[str] = None


_cache: Optional[DashboardSnapshot] = None
_lock = asyncio.Lock()

# Endpoint hostname -> s1SiteName, populated alongside _cache on every
# refresh_snapshot() call from the SAME list_inventory_items fetch this
# service already does every 5 minutes -- no new SentinelOne calls.
# Added 2026-08-18 for the alert-notification pipeline (capabilities/
# synergy.py): an alert's raw asset object only carries {id, name, type},
# no site -- confirmed live this session that list_inventory_items is the
# only source for s1SiteName, keyed by the item's own `name` field (=
# hostname, confirmed live: {'name': '3-LAP-546', 's1SiteName': '3line
# Limited', ...} on the same item). A plain in-memory dict lookup, so
# Phase 1's "well under a second" notification can use it too.
_endpoint_site_map: dict[str, str] = {}


def get_cached_snapshot() -> Optional[DashboardSnapshot]:
    return _cache


_priming_refresh_started = False


def get_site_for_endpoint(endpoint_name: str) -> Optional[str]:
    """Client/site name for a given endpoint hostname, or None if unknown
    (not yet in the cache, or genuinely has no site). Never makes a live
    call ITSELF -- purely a lookup against whatever the last
    refresh_snapshot() populated -- so this stays fast enough for Phase
    1's "well under a second" notification every time.

    Bug found live 2026-08-19: on a freshly-restarted daemon, Phase 1
    fired for the very first alert before daemon/scheduler.py's
    "sentinelone_client_map_refresh" task (interval=300s, run_on_start=
    True, but racing daemon startup with no ordering guarantee against
    the poller's own first cycle) had completed even once -- that
    alert's notification showed "unknown client" while the SAME
    finding's Phase 2 report (fired minutes later, after the scheduler
    had caught up) correctly resolved the real client name. Self-heals
    here: if the map is still completely empty (the map is real
    inventory data spanning hundreds of endpoints, so "empty" reliably
    means "never refreshed in this process yet", not "no clients"),
    kick off ONE background refresh (fire-and-forget, never awaited) so
    every call AFTER this one in the same process resolves correctly --
    this specific call still returns None/"unknown" this one time,
    since actually waiting on a live inventory fetch here would break
    Phase 1's own speed guarantee."""
    if not _endpoint_site_map:
        global _priming_refresh_started
        if not _priming_refresh_started:
            _priming_refresh_started = True
            try:
                import asyncio

                asyncio.create_task(refresh_snapshot())
            except RuntimeError:
                # No running event loop (e.g. called from sync/test code) --
                # nothing to prime against; next real async caller retries.
                _priming_refresh_started = False
    return _endpoint_site_map.get(endpoint_name)


async def _24h_start_ms(executor) -> Optional[int]:
    """Same get_timestamp_range -> iso_to_unix_timestamp pattern already
    established for DV hunts (services/sentinelone_recipe_executor.py) --
    reused here so "Active Alerts" reflects the last 24h, not an
    ever-growing all-time cumulative total (explicit user request,
    2026-08-05: dashboard alert counts didn't match "our 24hr context
    window"). Returns None on any failure so callers can fall back to an
    unfiltered (all-time) count rather than silently reporting zero."""
    ts, err = await executor._call("get_timestamp_range", {"hours": 24})
    if err or not isinstance(ts, dict):
        return None
    start_iso = ts.get("offset_time")
    if not start_iso:
        return None
    start_ms, err2 = await executor._call("iso_to_unix_timestamp", {"iso_datetime": start_iso})
    if err2:
        return None
    try:
        return int(start_ms)
    except (TypeError, ValueError):
        return None


async def _status_count(executor, status: str, since_ms: Optional[int] = None) -> int:
    filters = [{"fieldId": "status", "filterType": "string_equals", "value": status}]
    if since_ms is not None:
        filters.append({"fieldId": "createdAt", "filterType": "datetime_range", "start": since_ms})
    result, err = await executor._call(
        "search_alerts", {"filters": json.dumps(filters), "first": 1},
    )
    if err or not isinstance(result, dict):
        return 0
    return executor._total_count(result) or 0


async def _classification_count(executor, classification: str) -> int:
    """Alerts' `classification` field is filterable and uses the same
    camelCase `totalCount` shape as `status` -- confirmed live (Threat
    Landscape section build)."""
    result, err = await executor._call(
        "search_alerts",
        {"filters": json.dumps([{"fieldId": "classification", "filterType": "string_equals", "value": classification}]), "first": 1},
    )
    if err or not isinstance(result, dict):
        return 0
    return executor._total_count(result) or 0


async def _classification_counts(executor) -> dict[str, int]:
    """Sequential, not gathered: refresh_snapshot's top-level gather
    already fires ~11 concurrent SentinelOne calls (3 status + 4 vuln
    severity + 4 inside _sample_applications); adding 3 more fully
    concurrent classification calls on top of that pushed a live run to 15
    simultaneous calls and caused a timeout storm that zeroed out
    unrelated fields for that refresh cycle. Staggering these 3 keeps peak
    concurrency lower without slowing the (already 5-minute-interval,
    non-blocking) background refresh meaningfully."""
    counts: dict[str, int] = {}
    for classification in ["MALWARE", "RANSOMWARE", "MANUAL"]:
        counts[classification] = await _classification_count(executor, classification)
    return counts


async def _detection_source_sample(executor) -> list[dict]:
    """`detectionSource.product` is NOT a supported filter field for
    search_alerts (confirmed live: GraphQL "Field detectionSource.product
    does not exist or not supported for FILTER API call") -- so, same
    honest-sampling approach as _sample_applications, this pulls an
    unfiltered sample and aggregates client-side rather than presenting a
    filtered exact total that the API can't actually produce."""
    result, err = await executor._call(
        "search_alerts", {"filters": json.dumps([]), "first": 100},
    )
    if err or not isinstance(result, dict):
        return []
    counts: dict[str, int] = {}
    for row in executor._edges(result):
        product = (row.get("detectionSource") or {}).get("product")
        if product:
            counts[product] = counts.get(product, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": n, "count": c} for n, c in ranked]


async def _vuln_severity_count(executor, severity: str) -> int:
    result, err = await executor._call(
        "search_vulnerabilities",
        {"filters": json.dumps([{"fieldId": "severity", "filterType": "string_equals", "value": severity}]), "first": 1},
    )
    if err or not isinstance(result, dict):
        return 0
    return result.get("total_count") or 0


async def _vuln_critical_new_in_24h(executor, since_ms: Optional[int]) -> int:
    """Critical vulnerabilities are a STANDING risk total by nature (a
    vuln exists continuously until patched, unlike an alert) -- so unlike
    Active Alerts, this doesn't replace the all-time critical count, it
    adds a second, clearly-labeled "new in last 24h" figure alongside it
    (explicit user request, 2026-08-05: alerts/vulnerabilities didn't
    match "our 24hr context window"). `detectedAt` confirmed live as a
    valid search_vulnerabilities filter field (distinct from the
    response's own snake_case `detected_at`)."""
    if since_ms is None:
        return 0
    filters = [
        {"fieldId": "severity", "filterType": "string_equals", "value": "CRITICAL"},
        {"fieldId": "detectedAt", "filterType": "datetime_range", "start": since_ms},
    ]
    result, err = await executor._call(
        "search_vulnerabilities", {"filters": json.dumps(filters), "first": 1},
    )
    if err or not isinstance(result, dict):
        return 0
    return result.get("total_count") or 0


async def _sample_applications(executor) -> tuple[list[dict], set[str]]:
    """Same technique as services/sentinelone_recipe_executor.py's
    _execute_application_risk: a single severity sample is badly
    clustered, so sample all 4 concurrently and aggregate by
    software.name -- but the sample is used ONLY to discover which app
    names exist, never presented as their vulnerability count. Real
    counts (mismatch bug, 2026-08-04: dashboard showed raw sample-hit
    counts like 232/153 that didn't match anything in SentinelOne's own
    console, since a "hits in a 400-record sample" number isn't a
    vulnerability count at all) come from one exact_count follow-up
    query per app, same as the chat-side recipe already does.

    Also returns every distinct scope.group.name seen in the sample
    (explicit user request, 2026-08-05: recover groups without a current
    endpoint where possible) -- vulnerability records carry a group
    scope independent of InventoryItem's own s1GroupName, confirmed live
    2026-08-05, so a group that's invisible to the endpoint-derived list
    may still show up here via a vulnerability scoped to it."""
    async def _sample(severity: str) -> list[dict]:
        result, err = await executor._call(
            "search_vulnerabilities",
            {"filters": json.dumps([{"fieldId": "severity", "filterType": "string_equals", "value": severity}]), "first": 100},
        )
        if err or not isinstance(result, dict):
            return []
        return executor._edges(result)

    samples = await asyncio.gather(*(_sample(s) for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]))
    counts: dict[str, int] = {}
    groups_seen: set[str] = set()
    for sample in samples:
        for row in sample:
            name = (row.get("software") or {}).get("name")
            if name:
                counts[name] = counts.get(name, 0) + 1
            group_name = ((row.get("scope") or {}).get("group") or {}).get("name")
            if group_name:
                groups_seen.add(group_name)
    candidate_names = [name for name, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]]

    async def _exact_count(app_name: str) -> int:
        result, err = await executor._call(
            "search_vulnerabilities",
            {"filters": json.dumps([{"fieldId": "softwareName", "filterType": "string_equals", "value": app_name}]), "first": 1},
        )
        if err or not isinstance(result, dict):
            return 0
        return result.get("total_count") or 0

    # Sequential, not gathered -- refresh_snapshot's own top-level gather
    # already runs several other concurrent SentinelOne calls alongside
    # this one; 6 more fired at once here previously pushed a live run to
    # 15 simultaneous calls and caused a timeout storm (same root cause
    # already fixed once for _classification_counts). Staggering these 6
    # costs a few seconds on a background, 5-minute-interval refresh --
    # a fine trade for not zeroing out unrelated fields that cycle.
    exact_counts = [await _exact_count(n) for n in candidate_names]
    ranked = sorted(zip(candidate_names, exact_counts), key=lambda kv: kv[1], reverse=True)
    return [{"name": n, "count": c} for n, c in ranked], groups_seen


async def _critical_top_driver(executor, top_apps: list[dict], crit_total: int) -> Optional[dict]:
    """How much of the raw critical-vulnerability total does the single
    highest-vulnerability application account for -- live-confirmed
    (2026-08-05) that a couple of outdated, fleet-wide apps (e.g. one
    Chrome + one Firefox build present on most endpoints) can together
    drive the large majority of the fleet-wide critical row count, since
    each endpoint running them repeats the same large CVE list.

    Candidate names come from TWO sources, unioned, because either alone
    was live-confirmed (2026-08-05) to miss the true top driver: (a)
    _sample_applications' top_apps, ranked by ALL-SEVERITY exact count --
    can bury a CRITICAL-dominant app that isn't equally dominant in
    High/Medium/Low; (b) a single CRITICAL-only sample page -- unstable
    from one run to the next (a 100-row page missed Chrome even though
    Chrome's real exact CRITICAL count, 3125, beat Firefox's 2039).
    Exact-counting the union of both (capped at 5 names -- still a
    handful of sequential calls, same cost class as _sample_applications'
    own exact-count loop) reliably surfaces the real top driver."""
    if crit_total <= 0:
        return None

    sample_result, err = await executor._call(
        "search_vulnerabilities",
        {"filters": json.dumps([{"fieldId": "severity", "filterType": "string_equals", "value": "CRITICAL"}]), "first": 100},
    )
    sample_counts: dict[str, int] = {}
    if not err and isinstance(sample_result, dict):
        for row in executor._edges(sample_result):
            name = (row.get("software") or {}).get("name")
            if name:
                sample_counts[name] = sample_counts.get(name, 0) + 1
    sample_candidates = [name for name, _ in sorted(sample_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]]

    candidates: list[str] = []
    for name in [a["name"] for a in top_apps] + sample_candidates:
        if name not in candidates:
            candidates.append(name)
    candidates = candidates[:5]
    if not candidates:
        return None

    async def _critical_count_for(app_name: str) -> int:
        result, err2 = await executor._call(
            "search_vulnerabilities",
            {
                "filters": json.dumps([
                    {"fieldId": "softwareName", "filterType": "string_equals", "value": app_name},
                    {"fieldId": "severity", "filterType": "string_equals", "value": "CRITICAL"},
                ]),
                "first": 1,
            },
        )
        if err2 or not isinstance(result, dict):
            return 0
        return result.get("total_count") or 0

    # Sequential -- same concurrency-limit reason as every other follow-up
    # loop in this module.
    best_name, best_count = None, 0
    for name in candidates:
        count = await _critical_count_for(name)
        if count > best_count:
            best_name, best_count = name, count

    if not best_name or best_count <= 0:
        return None
    return {
        "name": best_name,
        "critical_count": best_count,
        "pct_of_total": round(100 * best_count / crit_total),
    }


async def refresh_snapshot() -> DashboardSnapshot:
    """Fetch a fresh structured snapshot directly via the same MCP tool
    calls the recipe layer uses (services.sentinelone_recipe_executor's
    _call/_edges/_total_count helpers) -- never invents a number, and
    falls back to the last-good cache (not zeros presented as real) if a
    refresh fails partway through."""
    global _cache
    from services import sentinelone_recipe_executor as executor

    if not executor.is_sentinelone_active():
        snapshot = DashboardSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(),
            tenant=executor._tenant_label(),
            sentinelone_active=False,
            error="SentinelOne is not connected",
        )
        async with _lock:
            _cache = snapshot
        return snapshot

    tenant = executor._tenant_label()
    try:
        # No `surface: "ENDPOINT"` filter -- confirmed live (2026-08-05) it
        # routes to a different underlying REST endpoint that silently
        # dropped one real, active endpoint (53 vs SentinelOne console's
        # 54). Dropping the filter matches the console exactly; same fix
        # applied throughout services/sentinelone_recipe_executor.py.
        inv_result, inv_err = await executor._call(
            "list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"}
        )
        items = inv_result.get("data", []) if isinstance(inv_result, dict) and not inv_err else []

        global _endpoint_site_map
        _endpoint_site_map = {
            i["name"]: i["s1SiteName"] for i in items if i.get("name") and i.get("s1SiteName")
        }

        since_ms = await _24h_start_ms(executor)

        (
            new_c, prog_c, resolved_c, crit_c, high_c, med_c, low_c, apps_result,
            classification_counts, detection_sources, crit_new_24h,
        ) = await asyncio.gather(
            _status_count(executor, "NEW", since_ms),
            _status_count(executor, "IN_PROGRESS", since_ms),
            _status_count(executor, "RESOLVED", since_ms),
            _vuln_severity_count(executor, "CRITICAL"),
            _vuln_severity_count(executor, "HIGH"),
            _vuln_severity_count(executor, "MEDIUM"),
            _vuln_severity_count(executor, "LOW"),
            _sample_applications(executor),
            _classification_counts(executor),
            _detection_source_sample(executor),
            _vuln_critical_new_in_24h(executor, since_ms),
        )
        top_apps, vuln_groups_seen = apps_result

        # Union endpoint-derived groups with groups seen via vulnerability
        # scope -- a group with zero current endpoints can still show up
        # here if any of its assets carries a vulnerability record
        # (explicit user request, 2026-08-05: recover groups without
        # endpoints where possible, rather than only ever reporting the
        # endpoint-derived subset).
        endpoint_groups = {i.get("s1GroupName") for i in items if i.get("s1GroupName")}
        all_groups = sorted(endpoint_groups | vuln_groups_seen)
        recovered_without_endpoint = sorted(vuln_groups_seen - endpoint_groups)

        top_driver = await _critical_top_driver(executor, top_apps, crit_c)

        snapshot = DashboardSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(),
            tenant=tenant,
            sentinelone_active=True,
            endpoint_count=len(items),
            endpoint_count_is_lower_bound=len(items) >= 1000,
            groups=all_groups,
            groups_without_current_endpoint=recovered_without_endpoint,
            accounts=sorted({i.get("s1AccountName") for i in items if i.get("s1AccountName")}),
            sites=sorted({i.get("s1SiteName") for i in items if i.get("s1SiteName")}),
            alerts_new=new_c,
            alerts_in_progress=prog_c,
            alerts_resolved=resolved_c,
            alerts_window_hours=24,
            vulnerabilities_critical=crit_c,
            vulnerabilities_high=high_c,
            vulnerabilities_medium=med_c,
            vulnerabilities_low=low_c,
            vulnerabilities_critical_new_24h=crit_new_24h,
            vulnerabilities_critical_top_driver=top_driver,
            # Bug fixed 2026-08-06: this used to check agent.networkStatus,
            # which live data proved doesn't track real connectivity at all
            # -- a machine confirmed stale for 3 real days (lastActiveDt
            # three days old) still reported networkStatus="connected",
            # and every endpoint sampled did too, regardless of actual
            # state. That's why this card kept showing "1 agent(s) offline"
            # the night most endpoints were actually down. agent.
            # consoleConnectivity is the field that actually varies with
            # real state (confirmed live: false for the same stale
            # machine, and for others, while networkStatus stayed
            # "connected" on all of them) -- it's also the field whose own
            # name matches what this card claims to report ("offline from
            # SentinelOne cloud" = not connected to the console).
            agents_offline=sum(1 for i in items if (i.get("agent") or {}).get("consoleConnectivity") is not True),
            top_applications=[ApplicationRisk(**a) for a in top_apps],
            endpoints_infected=sum(1 for i in items if i.get("infectionStatus") == "Infected"),
            endpoints_healthy=sum(1 for i in items if i.get("infectionStatus") == "Healthy"),
            threats_malware=classification_counts.get("MALWARE", 0),
            threats_ransomware=classification_counts.get("RANSOMWARE", 0),
            threats_manual=classification_counts.get("MANUAL", 0),
            detection_sources=[ApplicationRisk(**d) for d in detection_sources],
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Dashboard snapshot refresh failed: %s", e, exc_info=True)
        if _cache is not None:
            # Keep serving the last-good snapshot rather than present a
            # broken/zeroed one as current -- just note the staleness.
            _cache.error = f"refresh failed, showing last-known-good data: {e}"
            return _cache
        snapshot = DashboardSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(),
            tenant=tenant, sentinelone_active=True, error=str(e),
        )

    async with _lock:
        _cache = snapshot
    return snapshot


@dataclass
class SiteSummary:
    kind: str  # "found" | "not_configured" | "execution_error"
    site_name: str = ""
    endpoint_count: int = 0
    agents_offline: int = 0
    groups: list[str] = field(default_factory=list)
    error: Optional[str] = None


async def get_site_summary(site_name: str) -> SiteSummary:
    """Per-client EDR summary, for the client-detail view (2026-08-15).

    Deliberately narrower than the tenant-wide DashboardSnapshot: only
    endpoint_count/agents_offline/groups are included, because those are
    the fields genuinely derivable by filtering inventory rows by
    s1SiteName client-side. Alert and vulnerability counts are NOT
    included here -- search_alerts/search_vulnerabilities have no
    documented site-filtering field (every fieldId ever used against them
    is a flat scalar like status/severity/createdAt, confirmed by this
    session's exploration), so a per-site number for those would require
    genuinely new query logic this function doesn't attempt. Callers
    should keep showing tenant-wide alert/vuln figures alongside this,
    clearly labeled as tenant-wide, rather than mislabeling them as
    site-scoped.

    Makes its own list_inventory_items call rather than reusing
    get_cached_snapshot() -- refresh_snapshot() only persists aggregated
    counts, not the raw per-item list, so there's nothing cached at the
    per-item granularity this needs to filter on."""
    from services import sentinelone_recipe_executor as executor

    if not executor.is_sentinelone_active():
        return SiteSummary(kind="not_configured", site_name=site_name)

    try:
        inv_result, inv_err = await executor._call(
            "list_inventory_items", {"limit": 1000, "fetch_fields": "ALL"}
        )
        items = inv_result.get("data", []) if isinstance(inv_result, dict) and not inv_err else []
        site_items = [i for i in items if i.get("s1SiteName") == site_name]

        return SiteSummary(
            kind="found",
            site_name=site_name,
            endpoint_count=len(site_items),
            agents_offline=sum(
                1 for i in site_items if (i.get("agent") or {}).get("consoleConnectivity") is not True
            ),
            groups=sorted({i.get("s1GroupName") for i in site_items if i.get("s1GroupName")}),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Site summary fetch failed for %s: %s", site_name, e)
        return SiteSummary(kind="execution_error", site_name=site_name, error=str(e))


async def start_background_refresh() -> None:
    """Fire-and-forget loop -- refreshes the cache every
    REFRESH_INTERVAL_SECONDS regardless of whether anyone is viewing the
    dashboard. Call once at backend startup (mirrors the embedding
    pre-warm pattern already in backend/main.py)."""
    while True:
        try:
            await refresh_snapshot()
            logger.info("Dashboard snapshot refreshed")
        except Exception as e:  # noqa: BLE001
            logger.error("Dashboard background refresh iteration failed: %s", e, exc_info=True)
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
