"""Real-time SentinelOne dashboard snapshot endpoint.

Serves the background-refreshed cache from
services/sentinelone_dashboard_service.py (refreshed every 5 minutes,
started at backend startup) -- a page load never blocks on a live,
multi-call SentinelOne round-trip (~6s measured). If the cache is
completely empty (first request before the background loop's first pass
completes), triggers one synchronous refresh so the dashboard still shows
real data rather than an empty page.
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


@router.get("/sentinelone-overview")
async def get_sentinelone_overview():
    from services.sentinelone_dashboard_service import get_cached_snapshot, refresh_snapshot

    snapshot = get_cached_snapshot()
    if snapshot is None:
        snapshot = await refresh_snapshot()
    return asdict(snapshot)


@router.get("/strategic-insights")
async def get_strategic_insights():
    """Reads Sentry Agentic's own internal Finding store (populated by the
    SentinelOne ingestion daemon + Zeus's synergy analysis chain), not
    live SentinelOne data -- see services/strategic_insights_service.py's
    module docstring for why this is a distinct endpoint from
    /sentinelone-overview. Computed on each request (a bounded read over
    at most 500 internal rows), not cached -- unlike the live-SentinelOne
    snapshot, there's no external round-trip to protect against."""
    from services.strategic_insights_service import get_strategic_insights as compute

    insights = compute()
    return asdict(insights)
