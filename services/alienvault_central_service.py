"""AlienVault Central (USM Anywhere) integration -- built fresh for the
main backend, not adapted from soc_dashboard/ (explicit instruction,
2026-08-12: "do not work with what is on the soc dashboard. Build from
scratch").

A different AlienVault product from capabilities/reputation.py's OTX
pulse lookups: USM Anywhere is the multi-client SIEM/sensor platform,
authenticated via OAuth2 client_credentials (subdomain + client_id +
client_secret), not a single API key. One credential set here already
covers every client under this account (live-confirmed 2026-08-12
against cybervergent-central.alienvault.cloud: 200 OK, 8 deployments
returned from GET /api/1.1/deployments).

Non-secret fields (subdomain, client_id) are read via
core.config.get_integration_config() -- NOT os.getenv. The secret field
(client_secret) is read via _get_client_secret() (os.getenv() first,
falling back to backend.secrets_manager.get_secret()) -- NOT a bare
os.getenv() alone, since that only sees a secret on the exact process
that had set_secret() called on it directly (its os.environ mirror is
process-local); get_secret() reads the encrypted store itself, so a
freshly started backend process still finds a secret saved via the
Settings UI in an earlier process. This split matters:
services/integration_secrets.py + backend/api/config.py's
POST /config/integrations handler route ONLY registered *secret* fields
through set_secret() (-> encrypted store + os.environ); non-secret
fields land in the DB/JSON mirror only, read back through
get_integration_config(). Getting this backwards is a real, confirmed
bug elsewhere in this codebase (SentinelOne's api_url field never
becomes an env var; tools/alienvault_otx.py's api_key lookup is
similarly broken -- it expects the secret to come back from
get_integration_config(), which never happens). Do not repeat that here.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

INTEGRATION_ID = "alienvault-central"
_CLIENT_SECRET_ENV_VAR = "ALIENVAULT_CENTRAL_CLIENT_SECRET"

# Per-deployment credentials -- genuinely distinct from the central
# account's own client_id/client_secret above (live-confirmed 2026-08-15:
# the central credential gets a flat 401 trying to obtain a per-deployment
# token, on every deployment tested -- this account's per-deployment API
# access is gated behind separate, deployment-specific secrets). Shared
# client_id ("sentry" for this account, confirmed live) is stored as a
# normal non-secret config field like subdomain/client_id; the 8 (and
# counting) per-deployment secrets are stored as ONE JSON-blob secret
# rather than one secrets-manager entry per deployment -- registering N
# ad hoc integration-secret fields for a growing, account-specific list
# isn't a fit for services/integration_secrets.py's generic single-value-
# per-field model, and isn't exposed in the Settings UI form for the same
# reason. Set via a one-off script calling
# backend.secrets_manager.set_secret(_DEPLOYMENT_SECRETS_ENV_VAR, json.dumps(...))
# -- there's no UI path to edit this blob today; a future need to add/
# rotate a deployment's secret means re-running an equivalent script, not
# a silent gap to paper over.
_DEPLOYMENT_SECRETS_ENV_VAR = "ALIENVAULT_DEPLOYMENT_SECRETS_JSON"

# Module-level OAuth2 token cache -- one process-wide bearer token,
# refreshed on expiry. Deliberately not a class: exactly one AlienVault
# Central account is configured system-wide, no per-caller variation to
# justify instance state.
_token_cache: dict = {"token": None, "expiry": 0.0}


def _get_config() -> dict:
    from core.config import get_integration_config

    return get_integration_config(INTEGRATION_ID)


def _get_client_secret() -> Optional[str]:
    """Read the secret the way it's actually guaranteed to be found.

    A plain os.getenv() only sees this on the exact process that had
    set_secret() called on it directly (SecretsManager.set() mirrors
    into os.environ, but that's process-local) -- a freshly started
    backend process would come up blind to a secret saved via the
    Settings UI in an earlier process. backend.secrets_manager.get_secret()
    is the robust read path (its own priority order: encrypted store
    first, then os.environ, then .env), matching how the Settings UI's
    own save handler expects secrets to be read back. Same
    env-first-then-get_secret order as backend/api/soc_assistant.py's
    _expected_api_key(), for consistency.
    """
    value = os.getenv(_CLIENT_SECRET_ENV_VAR)
    if value:
        return value
    try:
        from backend.secrets_manager import get_secret

        return get_secret(_CLIENT_SECRET_ENV_VAR)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read %s from secrets manager: %s", _CLIENT_SECRET_ENV_VAR, e)
        return None


def _get_deployment_client_id() -> Optional[str]:
    """Shared client_id used for every deployment's own OAuth token
    (confirmed live 2026-08-15: "sentry" for this account) -- a plain
    non-secret config field, same as subdomain/client_id above."""
    return _get_config().get("deployment_client_id")


def _get_deployment_secrets() -> dict[str, str]:
    """{AVDeployment.name: per-deployment client_secret}. Same
    env-first-then-get_secret read order as _get_client_secret()."""
    raw = os.getenv(_DEPLOYMENT_SECRETS_ENV_VAR)
    if not raw:
        try:
            from backend.secrets_manager import get_secret

            raw = get_secret(_DEPLOYMENT_SECRETS_ENV_VAR)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not read %s from secrets manager: %s", _DEPLOYMENT_SECRETS_ENV_VAR, e)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to parse %s: %s", _DEPLOYMENT_SECRETS_ENV_VAR, e)
        return {}


def is_configured() -> bool:
    config = _get_config()
    return bool(
        config.get("subdomain")
        and config.get("client_id")
        and _get_client_secret()
    )


@dataclass
class AVDeployment:
    id: str
    name: str
    # fqdn/connection_status/authorized are all real, confirmed-live fields
    # on GET /deployments (2026-08-15 probe against this account) -- fqdn
    # is the deployment's own base URL host, used below for per-deployment
    # calls; connection_status/authorized are shown as-is in the client
    # detail view since they're real data, unlike alarm/event counts (see
    # get_deployment_alarms's docstring for why those aren't available yet).
    fqdn: Optional[str] = None
    connection_status: Optional[str] = None
    authorized: bool = False


@dataclass
class DeploymentsResult:
    kind: str  # "found" | "not_configured" | "execution_error"
    deployments: list[AVDeployment] = field(default_factory=list)
    error: Optional[str] = None


async def _get_token(subdomain: str, client_id: str, client_secret: str) -> Optional[str]:
    """OAuth2 client_credentials token, cached process-wide until expiry.
    Endpoint + grant shape confirmed live 2026-08-12 against
    cybervergent-central.alienvault.cloud (200 OK)."""
    if _token_cache["token"] and time.time() < _token_cache["expiry"]:
        return _token_cache["token"]

    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://{subdomain}/api/1.1/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        return None
    _token_cache["token"] = token
    _token_cache["expiry"] = time.time() + int(data.get("expires_in", 3600)) - 60
    return token


async def list_deployments() -> DeploymentsResult:
    """List every client deployment visible to this AlienVault Central
    account. Graceful, never raises -- same discipline as
    capabilities/reputation.py's provider checks."""
    config = _get_config()
    subdomain = config.get("subdomain")
    client_id = config.get("client_id")
    client_secret = _get_client_secret()
    if not (subdomain and client_id and client_secret):
        return DeploymentsResult(kind="not_configured")

    try:
        token = await _get_token(subdomain, client_id, client_secret)
        if not token:
            return DeploymentsResult(
                kind="execution_error", error="token request returned no access_token"
            )

        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://{subdomain}/api/1.1/deployments",
                headers={"Authorization": f"Bearer {token}"},
            )
        resp.raise_for_status()
        raw = resp.json()
        deployments = [
            AVDeployment(
                id=str(d.get("id") or d.get("name") or ""),
                name=d.get("name") or d.get("displayName") or "",
                fqdn=d.get("fqdn"),
                connection_status=d.get("connectionStatus"),
                authorized=bool(d.get("authorized")),
            )
            for d in raw
            if isinstance(d, dict) and (d.get("name") or d.get("displayName"))
        ]
        return DeploymentsResult(kind="found", deployments=deployments)
    except Exception as e:  # noqa: BLE001
        logger.error("AlienVault Central deployment listing failed: %s", e)
        return DeploymentsResult(kind="execution_error", error=str(e))


# ── Per-deployment alarms/events ──────────────────────────────────────────
#
# Real, live-confirmed limitation (2026-08-15 probe, 5 deployments):
# alarms/events are NOT reachable centrally (404 -- "the central URL does
# NOT host alarms, only individual deployment URLs do", matching
# soc_dashboard/fetcher.py's own comment on the same API), AND the
# CENTRAL account's client_id/client_secret is NOT authorized to obtain a
# token from any individual deployment's own oauth/token endpoint (a real
# Jetty-level 401 across every deployment tested, not a param/shape
# issue). This is structural, not fixable by rotating the central
# credential -- confirmed again the same day with a brand-new central
# credential, same 401.
#
# Resolved the same day: deployment-level access uses a SEPARATE
# credential per deployment (shared client_id "sentry" + one distinct
# client_secret per deployment, provided by the user) -- see
# _DEPLOYMENT_SECRETS_ENV_VAR above and _deployment_credentials() below.
# These are genuinely different from the central account's own
# client_id/client_secret, not a broader version of them. kind=
# "not_authorized" now means THIS deployment's own credential was
# missing/rejected, not "deployment-level access doesn't exist yet."

# Per-deployment OAuth2 token cache, keyed by fqdn -- separate from
# _token_cache above, which is the CENTRAL account's own token and must
# never be reused for a per-deployment call.
_deployment_token_cache: dict[str, dict] = {}


@dataclass
class AlarmsResult:
    kind: str  # "found" | "not_configured" | "not_authorized" | "execution_error"
    deployment_fqdn: str = ""
    hours_back: int = 24
    total: int = 0
    by_priority: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class EventCountResult:
    kind: str  # "found" | "not_configured" | "not_authorized" | "execution_error"
    deployment_fqdn: str = ""
    hours_back: int = 24
    total: int = 0
    error: Optional[str] = None


async def _get_deployment_token(fqdn: str, client_id: str, client_secret: str) -> Optional[str]:
    """Per-deployment OAuth2 token, cached per-fqdn until expiry. Confirmed
    live 2026-08-15: this account's central credential gets a 401 here
    (see module note above) -- callers must treat None as "not authorized
    for this deployment," not "transient failure worth retrying."""
    cached = _deployment_token_cache.get(fqdn)
    if cached and time.time() < cached["expiry"]:
        return cached["token"]

    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://{fqdn}/api/2.0/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
    if resp.status_code == 401:
        return None
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        return None
    _deployment_token_cache[fqdn] = {
        "token": token,
        "expiry": time.time() + int(data.get("expires_in", 3600)) - 60,
    }
    return token


def _time_window_ms(hours_back: int) -> tuple[int, int]:
    """(since_ms, now_ms) for a trailing window -- pure function, unit-
    testable without live calls. hours_back must be positive; callers
    (the API layer) are responsible for validating user-supplied values
    before this point."""
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - hours_back * 3600 * 1000
    return since_ms, now_ms


def _deployment_credentials(deployment: AVDeployment) -> Optional[tuple[str, str]]:
    """(client_id, client_secret) for this specific deployment's own API,
    or None if not configured for it. Deliberately NOT the central
    account's client_id/client_secret -- see the module note on
    _DEPLOYMENT_SECRETS_ENV_VAR above for why those are separate
    credentials entirely.

    Runtime-hardening gap fixed 2026-08-19 (tenant secrets isolation,
    defense-in-depth): _get_deployment_secrets() returns the full
    {deployment_name: secret} map for every client on this account --
    confirmed via a repo-wide grep this is the ONLY call site, so nothing
    else ever sees the full map, but nothing previously RECORDED which
    single client's secret actually got used on any given call either.
    This log line is what makes cross-client secret usage detectable
    after the fact -- it is NOT access control (this pass explicitly does
    not add authentication/authorization/per-tenant sandboxing, a
    materially bigger project than what was asked for here), just an
    audit trail. Logs the client/deployment name only, never the secret
    value itself."""
    client_id = _get_deployment_client_id()
    secrets = _get_deployment_secrets()
    secret = secrets.get(deployment.name)
    if not (client_id and secret):
        return None
    logger.info("AlienVault deployment credential accessed for client %r", deployment.name)
    return client_id, secret


async def get_deployment_alarms(deployment: AVDeployment, hours_back: int = 24) -> AlarmsResult:
    """Alarm count + priority/status breakdown for one client's AlienVault
    deployment, defaulting to a trailing 24-hour window (matches the
    AlienVault console's own default Alarms view -- confirmed via a live
    screenshot from the user, 2026-08-15) and always caller-overridable,
    never hardcoded past that default. Excludes suppressed alarms, no
    status filter (mirrors the console default: "Suppressed: Not
    Suppressed", "Alarm Status: Open OR In Review OR Closed" -- i.e. shown,
    not excluded).

    Time filter field name confirmed live 2026-08-15 against a real
    deployment: `timestamp_received_gte/lte` silently filters NOTHING
    (returned the full historical total, ~982K, mislabeled as "last 24h")
    -- `timestamp_occured_gte/lte` is the field that actually narrows
    results (confirmed: same account, same window, 19 results). Do not
    revert this without re-probing live; the wrong field name fails
    silently (200 OK, just unfiltered), not with an error."""
    if not deployment.fqdn:
        return AlarmsResult(kind="execution_error", hours_back=hours_back, error="deployment has no fqdn")

    creds = _deployment_credentials(deployment)
    if not creds:
        return AlarmsResult(kind="not_configured", deployment_fqdn=deployment.fqdn, hours_back=hours_back)
    client_id, client_secret = creds

    try:
        token = await _get_deployment_token(deployment.fqdn, client_id, client_secret)
        if not token:
            return AlarmsResult(
                kind="not_authorized", deployment_fqdn=deployment.fqdn, hours_back=hours_back,
                error="this deployment's credential was rejected (401) obtaining its own API token",
            )

        since_ms, now_ms = _time_window_ms(hours_back)
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://{deployment.fqdn}/api/2.0/alarms",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timestamp_occured_gte": since_ms,
                    "timestamp_occured_lte": now_ms,
                    "suppressed": "false",
                    "size": 200,
                },
            )
        resp.raise_for_status()
        body = resp.json()
        alarms = (body.get("_embedded") or {}).get("alarms", [])
        total = (body.get("page") or {}).get("totalElements", len(alarms))

        by_priority: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for a in alarms:
            p = a.get("priority_label") or "Unknown"
            s = a.get("status") or "Unknown"
            by_priority[p] = by_priority.get(p, 0) + 1
            by_status[s] = by_status.get(s, 0) + 1

        return AlarmsResult(
            kind="found", deployment_fqdn=deployment.fqdn, hours_back=hours_back,
            total=total, by_priority=by_priority, by_status=by_status,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("AlienVault alarms fetch failed for %s: %s", deployment.fqdn, e)
        return AlarmsResult(kind="execution_error", deployment_fqdn=deployment.fqdn, hours_back=hours_back, error=str(e))


async def get_deployment_event_count(deployment: AVDeployment, hours_back: int = 24) -> EventCountResult:
    """Total event count for one client's deployment over a trailing
    window, defaulting to 24h (same default/override contract as
    get_deployment_alarms). Time filter field confirmed live 2026-08-15:
    timestamp_occured_gte/lte narrows results here too (321,680 vs
    174,370,917 unfiltered, same account/window) -- same field as alarms,
    not a coincidence, use it consistently."""
    if not deployment.fqdn:
        return EventCountResult(kind="execution_error", hours_back=hours_back, error="deployment has no fqdn")

    creds = _deployment_credentials(deployment)
    if not creds:
        return EventCountResult(kind="not_configured", deployment_fqdn=deployment.fqdn, hours_back=hours_back)
    client_id, client_secret = creds

    try:
        token = await _get_deployment_token(deployment.fqdn, client_id, client_secret)
        if not token:
            return EventCountResult(
                kind="not_authorized", deployment_fqdn=deployment.fqdn, hours_back=hours_back,
                error="this deployment's credential was rejected (401) obtaining its own API token",
            )

        since_ms, now_ms = _time_window_ms(hours_back)
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://{deployment.fqdn}/api/2.0/events",
                headers={"Authorization": f"Bearer {token}"},
                params={"timestamp_occured_gte": since_ms, "timestamp_occured_lte": now_ms, "size": 1},
            )
        resp.raise_for_status()
        body = resp.json()
        total = (body.get("page") or {}).get("totalElements", 0)
        return EventCountResult(kind="found", deployment_fqdn=deployment.fqdn, hours_back=hours_back, total=total)
    except Exception as e:  # noqa: BLE001
        logger.error("AlienVault event count fetch failed for %s: %s", deployment.fqdn, e)
        return EventCountResult(kind="execution_error", deployment_fqdn=deployment.fqdn, hours_back=hours_back, error=str(e))
