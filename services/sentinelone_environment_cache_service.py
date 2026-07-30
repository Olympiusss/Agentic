"""Environment memory cache for the SentinelOne tenant.

Phase 2, Milestone 6. Holds the small, slow-changing facts the router and
the agent need on every turn without a live tool call: tenant sites, groups,
naming conventions (the account/site/group hierarchy), and token scope. This
is a *cache* of Milestone 1's environment map, not a new discovery
mechanism -- it never queries the live tenant itself.

Deliberately does not re-run live discovery on a schedule. The build
brief's own guardrail is "ask before running anything broad or expensive"
against the live tenant; an unattended background timer hitting a security
product's API without a human in the loop each time would violate that
spirit, even for a cheap query. Refreshing instead means re-reading
`environment_map.yaml` for `refresh_interval_seconds()` (so the cache picks
up a re-run of `scripts/discover_sentinelone_environment.py --confirm-dv`,
which stays the explicit, human-approved way to get fresh live data). See
`daemon/scheduler.py`'s `sentinelone_environment_cache_refresh` task, which
follows the same `is_enabled()`/interval pattern as `ThreatFeedPoller`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_ROOT = REPO_ROOT / "data" / "knowledge" / "sentinelone"
ENVIRONMENT_MAP_PATH = KNOWLEDGE_ROOT / "environment_map.yaml"
CACHE_STATE_PATH = KNOWLEDGE_ROOT / "environment_cache_state.json"

DEFAULT_REFRESH_INTERVAL_SECONDS = 6 * 3600


@dataclass
class EnvironmentCache:
    generated_at: Optional[str] = None
    refreshed_at: Optional[str] = None
    source: str = ENVIRONMENT_MAP_PATH.name
    sites: dict[str, str] = field(default_factory=dict)
    groups: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, str] = field(default_factory=dict)
    naming_convention: Optional[str] = None
    scope_paths_observed: list[str] = field(default_factory=list)
    token_scope: Optional[str] = None
    key_hosts_sample_size: int = 0
    note: Optional[str] = None


class SentinelOneEnvironmentCacheService:
    """Loads and periodically refreshes the environment memory cache."""

    _cache: Optional[EnvironmentCache] = None

    @staticmethod
    def is_enabled() -> bool:
        return (
            bool(
                os.getenv("SENTINELONE_API_TOKEN")
                and os.getenv("SENTINELONE_CONSOLE_URL")
            )
            and ENVIRONMENT_MAP_PATH.exists()
        )

    @staticmethod
    def refresh_interval_seconds() -> int:
        try:
            return max(
                300,
                int(
                    os.getenv(
                        "SENTINELONE_ENV_CACHE_REFRESH_INTERVAL",
                        str(DEFAULT_REFRESH_INTERVAL_SECONDS),
                    )
                ),
            )
        except (TypeError, ValueError):
            return DEFAULT_REFRESH_INTERVAL_SECONDS

    @classmethod
    def refresh(cls) -> EnvironmentCache:
        """Rebuild the cache from environment_map.yaml. Cheap and local --
        does not call the live tenant. Persists a small state file recording
        when the refresh ran, for observability."""
        if not ENVIRONMENT_MAP_PATH.exists():
            raise FileNotFoundError(
                f"{ENVIRONMENT_MAP_PATH} does not exist -- run "
                "scripts/discover_sentinelone_environment.py --confirm-dv first."
            )
        with open(ENVIRONMENT_MAP_PATH, "r", encoding="utf-8") as f:
            env_map = yaml.safe_load(f)

        identity = env_map.get("tenant", {}).get("identity", {})
        hierarchy = env_map.get("hierarchy", {})
        sample_size = env_map.get("endpoints", {}).get("sample_size", 0)
        now = datetime.now(timezone.utc).isoformat()

        cache = EnvironmentCache(
            generated_at=env_map.get("generated_at"),
            refreshed_at=now,
            accounts=identity.get("accounts", {}),
            sites=identity.get("sites", {}),
            groups=identity.get("groups", {}),
            naming_convention=hierarchy.get("note"),
            scope_paths_observed=hierarchy.get("scope_paths_observed", []),
            token_scope=(
                "single tenant, single account -- this MCP server has no "
                "cross-tenant/cross-account tool; token scope is implicitly "
                "this one connected tenant (confirmed Milestone 0/1)"
            ),
            key_hosts_sample_size=sample_size,
            note=(
                f"key_hosts is a discovery sample size only ({sample_size} "
                "endpoints), not a full tenant census -- do not report it "
                "as a total endpoint count."
            ),
        )
        cls._cache = cache

        CACHE_STATE_PATH.write_text(
            json.dumps(asdict(cache), indent=2), encoding="utf-8"
        )
        logger.info("SentinelOne environment cache refreshed at %s", now)
        return cache

    @classmethod
    def get(cls) -> EnvironmentCache:
        if cls._cache is None:
            cls.refresh()
        return cls._cache

    @classmethod
    def as_dict(cls) -> dict[str, Any]:
        return asdict(cls.get())
