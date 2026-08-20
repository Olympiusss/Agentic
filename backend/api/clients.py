"""Client registry endpoint -- EDR/SIEM/Both platform coverage per client.

Serves the background-refreshed cache from
services/client_registry_service.py (refreshed every 10 minutes,
started at backend startup) -- a page load never blocks on a live
SentinelOne + AlienVault round-trip. If the cache is completely empty
(first request before the background loop's first pass completes),
triggers one synchronous refresh so the page still shows real data.
"""

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/clients", tags=["clients"])
logger = logging.getLogger(__name__)


class OverrideRequest(BaseModel):
    s1_site_name: str
    av_deployment_name: str


@router.get("/")
async def list_clients():
    from services.client_registry_service import get_cached_snapshot, refresh_snapshot

    snapshot = get_cached_snapshot()
    if snapshot is None:
        snapshot = await refresh_snapshot()
    return asdict(snapshot)


@router.post("/overrides")
async def create_override(body: OverrideRequest):
    """Admin-confirmed pairing for a client the automatic name-matcher
    couldn't bridge (e.g. SentinelOne's formal display name vs.
    AlienVault's slug-style deployment name). Re-runs the match
    immediately so the response reflects it, rather than waiting for
    the next background refresh cycle."""
    from services.client_registry_service import add_override, refresh_snapshot

    add_override(body.s1_site_name, body.av_deployment_name)
    snapshot = await refresh_snapshot()
    return asdict(snapshot)


@router.delete("/overrides/{s1_site_name}")
async def delete_override(s1_site_name: str):
    from services.client_registry_service import refresh_snapshot, remove_override

    remove_override(s1_site_name)
    snapshot = await refresh_snapshot()
    return asdict(snapshot)


@router.get("/{name}/detail")
async def get_client_detail(name: str, hours_back: int = Query(default=24, ge=1, le=720)):
    """Per-client EDR and/or SIEM detail for the dashboard's client-detail
    panel. `hours_back` defaults to 24h -- matching AlienVault's own
    console default (confirmed via a live screenshot, 2026-08-15) -- and
    is always caller-overridable (1h-30d range) rather than fixed.

    Returns whichever of `edr`/`siem` the client actually has; the other
    is omitted, not zeroed, so the frontend can distinguish "no data
    returned" from "genuinely zero."
    """
    from services.alienvault_central_service import AVDeployment, get_deployment_alarms, get_deployment_event_count
    from services.client_registry_service import find_client, get_cached_snapshot, refresh_snapshot
    from services.sentinelone_dashboard_service import get_site_summary

    # find_client() reads the module-level cache directly and returns None
    # on a cold cache -- real bug, live 2026-08-15: right after a backend
    # restart, this 404'd for a real client because client_registry_
    # service's background loop hadn't completed its first refresh yet.
    # list_clients() below already has this fallback; find_client() itself
    # doesn't, since it's also called from the SOC Assistant path where a
    # forced live refresh mid-request isn't always wanted -- so the
    # fallback belongs here, not inside find_client().
    if get_cached_snapshot() is None:
        await refresh_snapshot()

    record = find_client(name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown client: {name}")

    result: dict = {"name": record.name, "hours_back": hours_back}

    if record.has_edr and record.s1_site_name:
        result["edr"] = asdict(await get_site_summary(record.s1_site_name))

    if record.has_siem and record.av_deployment_name:
        deployment = AVDeployment(
            id=record.av_deployment_name, name=record.av_deployment_name, fqdn=record.av_deployment_fqdn
        )
        alarms, events = await asyncio.gather(
            get_deployment_alarms(deployment, hours_back),
            get_deployment_event_count(deployment, hours_back),
        )
        result["siem"] = {"alarms": asdict(alarms), "events": asdict(events)}

    return result
