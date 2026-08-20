"""Client registry -- EDR (SentinelOne) / SIEM (AlienVault Central) /
Both detection per client. Visibility-only feature (explicit scope,
confirmed 2026-08-12): no RBAC/data-isolation changes, every analyst
still sees everything. Computed fresh each refresh cycle, not
persisted -- no DB migration needed for a purely informational view.

Reuses services/sentinelone_dashboard_service.py's already-cached
`sites` list rather than polling SentinelOne a second time (that
service already refreshes every 5 minutes on its own background loop;
a second independent SentinelOne poll here would be redundant load for
no benefit). Combines it with services/alienvault_central_service.py's
deployment list (built fresh this pass -- not soc_dashboard's fetcher,
per explicit instruction not to reuse that subproject).

Matching is name-based -- the only lever available on either side: the
existing SentinelOne snapshot exposes site *names* only (no site ID;
purple-mcp has no dedicated sites-listing tool, confirmed by Milestone
9), and AlienVault deployments have no foreign key to anything
SentinelOne-side. Exact normalized match first, substring-containment
fallback tagged "fuzzy", everything left over surfaces as its own
single-platform record rather than being silently dropped or guessed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 600  # 10 min -- platform mix changes slowly

# Manual overrides for client-name pairs the automatic matcher can't
# bridge (real example, live-confirmed 2026-08-15: SentinelOne's
# "Zone Payment Network Limited" and AlienVault's "zonenetwork" are the
# same client, but share no contiguous substring after normalization --
# no generic heuristic reliably closes this class of gap, since S1's
# formal display names and AV's slug-style deployment names follow
# unrelated conventions). {s1_site_name: av_deployment_name}. A JSON
# file, not a DB table -- same "computed + cached, no migration" choice
# as the rest of this module; this is small admin-maintained state, not
# a new source of truth.
_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "client_registry_overrides.json"

# Trailing tokens real client names carry on one side but not the other
# (sensor/deployment naming conventions), stripped before comparison.
# Informed by soc_dashboard's independently-learned list of the same
# problem -- domain knowledge about how these two platforms name
# things, not soc_dashboard's code, which this module does not import.
_STRIP_SUFFIXES = ("usm sensor", "usm anywhere", "sensor", "edr", "siem", "nfr")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def _normalize(name: str) -> str:
    """Pure function, directly unit-testable -- no I/O."""
    n = _PUNCT_RE.sub(" ", name.lower())
    n = _WS_RE.sub(" ", n).strip()
    for suffix in _STRIP_SUFFIXES:
        if n == suffix:
            return ""
        if n.endswith(" " + suffix):
            n = n[: -(len(suffix) + 1)].strip()
    return n


def client_id_for_record(record: "ClientRecord") -> str:
    """Stable string slug for a ClientRecord, e.g. "cybervergent" for
    "MU ||EXN ROA - Upfront - CyberVergent Ltd". Public (unified-schema
    foundation, 2026-08-20) and used by BOTH `_sync_clients_table()`
    below and `services/ingestion_service.py`'s ingestion-time
    resolution -- deliberately the same function in both places so a
    `Finding.client_id` and a `clients.client_id` row always agree on
    what a given client's slug is. Built directly on this module's own
    `_normalize()` rather than a separate slugifier."""
    return _normalize(record.name).replace(" ", "-")


@dataclass
class ClientRecord:
    name: str
    has_edr: bool = False
    has_siem: bool = False
    s1_site_name: Optional[str] = None
    av_deployment_name: Optional[str] = None
    # Populated in refresh_snapshot() (not _match(), which stays a pure
    # name-only function for testability) -- the client-detail endpoint
    # needs the deployment's fqdn to call
    # alienvault_central_service.get_deployment_alarms/get_deployment_event_count,
    # which take an AVDeployment, not just a name string.
    av_deployment_fqdn: Optional[str] = None
    # "exact" | "fuzzy" | "manual" | None -- None means single-platform,
    # nothing to match against on the other side.
    match_confidence: Optional[str] = None
    # Unified-schema foundation, 2026-08-20: the real, persisted clients.client_id
    # this record maps to -- populated in refresh_snapshot(), not _match()
    # (which stays a pure name-only function for testability).
    client_id: Optional[str] = None


@dataclass
class ClientRegistrySnapshot:
    generated_at: str
    clients: list[ClientRecord] = field(default_factory=list)
    edr_only: int = 0
    siem_only: int = 0
    both: int = 0
    total: int = 0
    sentinelone_active: bool = False
    alienvault_configured: bool = False
    error: Optional[str] = None


_cache: Optional[ClientRegistrySnapshot] = None
_lock = asyncio.Lock()


def get_cached_snapshot() -> Optional[ClientRegistrySnapshot]:
    return _cache


def _match(
    s1_names: list[str], av_names: list[str], overrides: Optional[dict[str, str]] = None
) -> list[ClientRecord]:
    """Pure matching function -- no I/O -- so it's directly
    unit-testable without live SentinelOne/AlienVault calls.

    overrides: {s1_site_name: av_deployment_name}, admin-confirmed pairs
    that win over automatic matching regardless of what the name strings
    look like. Applied by exact original-name lookup (not normalized --
    an override is keyed to the literal names the admin picked from a
    real snapshot), so a stale override (either side renamed/removed)
    simply fails to apply rather than mismatching something else -- it
    stays in the file, ready to reapply if the name reappears, and both
    sides fall through to normal automatic matching in the meantime."""
    s1_remaining = {name: _normalize(name) for name in s1_names}
    av_remaining = {name: _normalize(name) for name in av_names}
    records: list[ClientRecord] = []

    # Pass 0: admin-confirmed manual overrides, before any automatic
    # matching gets a chance to (mis)pair either side.
    for s1_name, av_name in (overrides or {}).items():
        if s1_name in s1_remaining and av_name in av_remaining:
            records.append(ClientRecord(
                name=s1_name, has_edr=True, has_siem=True,
                s1_site_name=s1_name, av_deployment_name=av_name,
                match_confidence="manual",
            ))
            del s1_remaining[s1_name]
            del av_remaining[av_name]

    # Pass 1: exact normalized match.
    for s1_name, s1_norm in list(s1_remaining.items()):
        if not s1_norm:
            continue
        for av_name, av_norm in list(av_remaining.items()):
            if av_norm and s1_norm == av_norm:
                records.append(ClientRecord(
                    name=s1_name, has_edr=True, has_siem=True,
                    s1_site_name=s1_name, av_deployment_name=av_name,
                    match_confidence="exact",
                ))
                del s1_remaining[s1_name]
                del av_remaining[av_name]
                break

    # Pass 2: substring-containment fuzzy match among what's left.
    for s1_name, s1_norm in list(s1_remaining.items()):
        if not s1_norm:
            continue
        for av_name, av_norm in list(av_remaining.items()):
            if av_norm and (av_norm in s1_norm or s1_norm in av_norm):
                records.append(ClientRecord(
                    name=s1_name, has_edr=True, has_siem=True,
                    s1_site_name=s1_name, av_deployment_name=av_name,
                    match_confidence="fuzzy",
                ))
                del s1_remaining[s1_name]
                del av_remaining[av_name]
                break

    # Whatever's left on either side is single-platform -- surfaced
    # explicitly, never dropped and never guessed into a false match.
    for s1_name in s1_remaining:
        records.append(ClientRecord(name=s1_name, has_edr=True, s1_site_name=s1_name))
    for av_name in av_remaining:
        records.append(ClientRecord(name=av_name, has_siem=True, av_deployment_name=av_name))

    return sorted(records, key=lambda r: r.name.lower())


def _load_overrides() -> dict[str, str]:
    if not _OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to load client registry overrides: %s", e)
        return {}


def _save_overrides(overrides: dict[str, str]) -> None:
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OVERRIDES_PATH.write_text(json.dumps(overrides, indent=2, sort_keys=True), encoding="utf-8")


def add_override(s1_site_name: str, av_deployment_name: str) -> dict[str, str]:
    """Record an admin-confirmed pairing. Takes effect on the next
    refresh_snapshot() call -- callers that need it reflected
    immediately should await refresh_snapshot() right after."""
    overrides = _load_overrides()
    overrides[s1_site_name] = av_deployment_name
    _save_overrides(overrides)
    return overrides


def remove_override(s1_site_name: str) -> dict[str, str]:
    overrides = _load_overrides()
    overrides.pop(s1_site_name, None)
    _save_overrides(overrides)
    return overrides


async def refresh_snapshot() -> ClientRegistrySnapshot:
    global _cache
    from services import alienvault_central_service, sentinelone_dashboard_service

    # Force a fresh dashboard check whenever the cache is empty OR claims
    # inactive -- not just when it's None. Real bug hit live 2026-08-15:
    # this service's own background loop starts at backend startup
    # alongside sentinelone_dashboard_service's, and purple-mcp/SentinelOne
    # connects relatively late in the startup sequence (after several
    # other MCP servers fail/timeout) -- if this loop's first refresh_
    # snapshot() call raced ahead of that connection, it read a real but
    # transient "sentinelone_active=False" snapshot and cached it, then
    # didn't check again for a full REFRESH_INTERVAL_SECONDS (10 min) even
    # after SentinelOne finished connecting seconds later and the
    # dashboard's OWN cache had already self-corrected. Trusting a cached
    # "inactive" read is exactly the wrong call here -- inactive is the
    # state most likely to be a startup-race artifact, not truth.
    s1_snapshot = sentinelone_dashboard_service.get_cached_snapshot()
    if s1_snapshot is None or not s1_snapshot.sentinelone_active:
        s1_snapshot = await sentinelone_dashboard_service.refresh_snapshot()
    s1_active = bool(s1_snapshot and s1_snapshot.sentinelone_active)
    s1_sites = list(s1_snapshot.sites) if s1_active else []

    av_result = await alienvault_central_service.list_deployments()
    av_by_name = {d.name: d for d in av_result.deployments} if av_result.kind == "found" else {}
    av_names = list(av_by_name.keys())

    records = _match(s1_sites, av_names, overrides=_load_overrides())
    for r in records:
        if r.av_deployment_name and r.av_deployment_name in av_by_name:
            r.av_deployment_fqdn = av_by_name[r.av_deployment_name].fqdn
        r.client_id = client_id_for_record(r)

    both = sum(1 for r in records if r.has_edr and r.has_siem)
    edr_only = sum(1 for r in records if r.has_edr and not r.has_siem)
    siem_only = sum(1 for r in records if r.has_siem and not r.has_edr)

    snapshot = ClientRegistrySnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        clients=records,
        edr_only=edr_only, siem_only=siem_only, both=both, total=len(records),
        sentinelone_active=s1_active,
        alienvault_configured=av_result.kind != "not_configured",
        error=av_result.error if av_result.kind == "execution_error" else None,
    )
    async with _lock:
        _cache = snapshot
    await _sync_clients_table(snapshot)
    return snapshot


async def _sync_clients_table(snapshot: ClientRegistrySnapshot) -> None:
    """Upsert this snapshot's records into the real, persisted `clients`
    table (unified-schema foundation, 2026-08-20) -- the additive tail
    of refresh_snapshot(), not a separate/parallel poller. Best-effort:
    a persistence failure here must never break the in-memory snapshot
    this module has always served, same philosophy as
    capabilities/synergy.py's _write_blackboard.

    Rename-drift handling: matches on the more stable s1_site_name/
    av_deployment_name first (falling back to client_id only for a
    brand-new row), and logs a warning on any detected rename rather
    than silently drifting -- acceptable for this volume of enterprise
    client-onboarding data (a rare event), not per-request state.
    """
    try:
        from database.connection import get_db_manager
        from database.models import Client

        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            for r in snapshot.clients:
                if not r.client_id:
                    continue
                existing = session.get(Client, r.client_id)
                if existing is None and r.s1_site_name:
                    existing = (
                        session.query(Client)
                        .filter(Client.s1_site_name == r.s1_site_name)
                        .first()
                    )
                if existing is None and r.av_deployment_name:
                    existing = (
                        session.query(Client)
                        .filter(Client.av_deployment_name == r.av_deployment_name)
                        .first()
                    )
                if existing is not None and existing.client_id != r.client_id:
                    logger.warning(
                        "Client registry: %r appears renamed (client_id %r -> %r) "
                        "-- keeping the existing row's client_id to avoid breaking "
                        "already-scoped findings/users; update manually if this is "
                        "a genuine rename.",
                        r.name, existing.client_id, r.client_id,
                    )
                    r.client_id = existing.client_id
                elif existing is None:
                    existing = Client(client_id=r.client_id)
                    session.add(existing)

                existing.display_name = r.name
                existing.s1_site_name = r.s1_site_name
                existing.av_deployment_name = r.av_deployment_name
                existing.av_deployment_fqdn = r.av_deployment_fqdn
                existing.match_confidence = r.match_confidence
                existing.is_active = True
    except Exception as e:  # noqa: BLE001
        logger.error("Client registry: failed to sync clients table: %s", e)


async def start_background_refresh() -> None:
    """Fire-and-forget loop, mirrors
    services/sentinelone_dashboard_service.py's start_background_refresh.
    Call once at backend startup."""
    while True:
        try:
            await refresh_snapshot()
            logger.info("Client registry snapshot refreshed")
        except Exception as e:  # noqa: BLE001
            logger.error("Client registry background refresh iteration failed: %s", e, exc_info=True)
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


def find_client(name: str) -> Optional[ClientRecord]:
    """Case-insensitive lookup by exact or normalized name -- used by
    the SOC Assistant API contract to ground a `client` field against
    what's actually known. Returns None (not a guess) if nothing in the
    current snapshot matches."""
    if not _cache:
        return None
    target = name.strip().lower()
    target_norm = _normalize(name)
    for record in _cache.clients:
        if record.name.strip().lower() == target:
            return record
    if target_norm:
        for record in _cache.clients:
            if _normalize(record.name) == target_norm:
                return record
    return None
