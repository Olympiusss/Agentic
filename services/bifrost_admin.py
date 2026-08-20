"""Bifrost management API helper.

Bifrost exposes a REST admin API at ``${BIFROST_URL}/api/providers/{name}``
that lets us update provider keys at runtime without a container restart.
This module is the one place the backend talks to that API, so the flow
is: user edits a key in the UI → ``llm_providers`` endpoint writes to the
secrets manager → this module pushes the new value to Bifrost → Bifrost
uses it for subsequent requests.

The previous architecture had Bifrost read ``env.ANTHROPIC_API_KEY`` from
its container env, which diverged from whatever the UI had written to the
secrets manager under ``llm_provider_<id>_api_key``. Pushing via the API
keeps a single source of truth in the secrets manager.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5.0

# In-flight future used to coalesce concurrent ``sync_all_provider_models``
# calls. If a sync is running and a second caller arrives (e.g. a cold
# dropdown lazy-sync landing during the scheduled refresher's iteration),
# the second caller awaits the same future instead of issuing a duplicate
# round of upstream fetches. None when idle.
_sync_in_flight: Optional["asyncio.Future[Dict[str, Any]]"] = None


def _bifrost_base_url() -> str:
    return os.getenv("BIFROST_URL", "http://localhost:8080").rstrip("/")


def _get_provider(name: str, client: httpx.Client) -> Optional[Dict[str, Any]]:
    try:
        r = client.get(
            f"{_bifrost_base_url()}/api/providers/{name}", timeout=_DEFAULT_TIMEOUT
        )
        if r.status_code == 404:
            logger.debug("Bifrost: provider %s not configured", name)
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("Bifrost: could not fetch provider %s: %s", name, e)
        return None


def _key_name_for_row(row_provider_id: str) -> str:
    """Deterministic Bifrost key name for one LLMProviderConfig row, so
    repeated pushes update the same Bifrost key instead of accumulating
    duplicates."""
    return f"sentry-agentic-{row_provider_id}"


def _find_key_by_name(provider_name: str, key_name: str, client: httpx.Client) -> Optional[Dict[str, Any]]:
    try:
        r = client.get(
            f"{_bifrost_base_url()}/api/providers/{provider_name}/keys",
            timeout=_DEFAULT_TIMEOUT,
        )
        if r.status_code >= 400:
            return None
        for k in r.json().get("keys") or []:
            if k.get("name") == key_name:
                return k
    except Exception as e:  # noqa: BLE001
        logger.debug("Bifrost: could not list keys for %s: %s", provider_name, e)
    return None


# Bifrost picks among every key that lists a requested model using this
# weight, independent of anything in our own DB -- our "is_default" flag
# has zero effect on Bifrost's own routing unless we tell it to via this
# field. Live-confirmed 2026-08-06: an old, exhausted, unmanaged key
# ("default-anthropic-key", sourced from Bifrost's own env var, weight 1)
# legitimately lists the same models our managed keys do (model listing
# reflects account access, not remaining credit), and every key we ever
# pushed defaulted to weight 0 -- so Bifrost kept preferring the exhausted
# key for any shared model regardless of which row the UI marked default.
# High/low here just needs to decisively outrank an unmanaged weight-1
# key; the exact numbers aren't meaningful beyond that ordering.
DEFAULT_ROW_WEIGHT = 10
NON_DEFAULT_ROW_WEIGHT = 1


def push_provider_key(
    provider_name: str,
    key_value: str,
    row_provider_id: Optional[str] = None,
    models: Optional[List[str]] = None,
    weight: Optional[int] = None,
) -> bool:
    """Create or update Sentry Agentic's key entry on ``provider_name``.

    Bug fixed 2026-08-06: this previously GET/mutate/PUT'd the whole
    provider document at ``/api/providers/{name}`` -- confirmed live
    that endpoint flatly rejects a "keys" field ("keys are not accepted
    on this endpoint; use POST/PUT /api/providers/{provider}/keys[/
    {key_id}] to manage keys"), so every push silently failed and
    switching the default LLM provider never actually changed which
    credential Bifrost used for a request. Also explains why GET never
    showed a "keys" array on the provider document -- keys are a
    separate sub-resource entirely, not a field of it. The one key that
    DID work (the original bootstrap default) turned out to be sourced
    from Bifrost's own ``env.ANTHROPIC_API_KEY`` container env, a
    leftover of the pre-admin-API architecture this module's own
    docstring already describes as superseded -- its model list
    predates newer model releases, which is why requests for those
    models failed with "could not auto resolve a provider" (no key
    anywhere had them in its allow-list).

    Keyed by a deterministic name (``_key_name_for_row``) so repeated
    calls (e.g. every "Set as default" click) update the same Bifrost
    key instead of accumulating duplicates -- PUT to update if a
    matching key is found, POST to create if not. ``row_provider_id``
    defaults to ``provider_name`` for callers that don't have the DB
    row id handy (keeps this a no-op-safe single Bifrost key per
    provider_type in that case, matching the old assumption).

    ``weight`` controls Bifrost's own preference among every key that
    lists a requested model -- see ``DEFAULT_ROW_WEIGHT``/
    ``NON_DEFAULT_ROW_WEIGHT`` above. Omitted means "don't change it"
    (preserves whatever's already on an existing key; a brand new key
    falls to whatever Bifrost itself defaults an unspecified weight to).

    Returns True on success. Any failure is logged and returns False so
    the caller's CRUD flow never breaks on a Bifrost hiccup.
    """
    if not provider_name:
        return False
    key_name = _key_name_for_row(row_provider_id or provider_name)
    body: Dict[str, Any] = {
        "name": key_name,
        "value": {"value": key_value, "env_var": "", "from_env": False},
    }
    if models:
        body["models"] = models
    if weight is not None:
        body["weight"] = weight
    with httpx.Client() as client:
        existing = _find_key_by_name(provider_name, key_name, client)
        try:
            if existing and existing.get("id"):
                if models is None and existing.get("models"):
                    # Preserve whatever allow-list is already there when the
                    # caller isn't explicitly changing it (e.g. a plain key
                    # rotation shouldn't wipe a previously-synced model list).
                    body["models"] = existing["models"]
                if weight is None and existing.get("weight") is not None:
                    # Same preservation rule as models: don't silently reset
                    # weight to Bifrost's default on an unrelated update.
                    body["weight"] = existing["weight"]
                r = client.put(
                    f"{_bifrost_base_url()}/api/providers/{provider_name}/keys/{existing['id']}",
                    json=body,
                    timeout=_DEFAULT_TIMEOUT,
                )
            else:
                r = client.post(
                    f"{_bifrost_base_url()}/api/providers/{provider_name}/keys",
                    json=body,
                    timeout=_DEFAULT_TIMEOUT,
                )
            if r.status_code >= 400:
                logger.warning(
                    "Bifrost: %s /api/providers/%s/keys returned %s: %s",
                    "PUT" if existing else "POST",
                    provider_name,
                    r.status_code,
                    r.text[:200],
                )
                return False
            logger.info(
                "Bifrost: %s key '%s' for provider %s",
                "updated" if existing else "created",
                key_name,
                provider_name,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Bifrost: key push for %s failed: %s", provider_name, e)
            return False


def sync_all_provider_keys() -> Dict[str, bool]:
    """Push every DB-configured provider's current secret value to Bifrost.

    Run on backend startup so Bifrost picks up whatever is in the secrets
    store regardless of how it was started or whether its container was
    recreated. Best-effort — returns a per-provider dict of success flags.
    """
    # Deferred imports to keep this module import-cheap for code that only
    # needs ``push_provider_key`` (e.g. llm_providers.py).
    from backend.secrets_manager import get_secret
    from database.connection import get_db_manager
    from database.models import LLMProviderConfig

    results: Dict[str, bool] = {}
    db_manager = get_db_manager()
    if db_manager._engine is None:
        db_manager.initialize()
    with db_manager.session_scope() as session:
        rows = (
            session.query(LLMProviderConfig)
            .filter(
                LLMProviderConfig.is_active.is_(True),
            )
            .all()
        )
        for row in rows:
            if not row.api_key_ref:
                continue
            value = get_secret(row.api_key_ref)
            if not value:
                logger.debug(
                    "Bifrost sync: no value in secrets store for %s (ref=%s)",
                    row.provider_id,
                    row.api_key_ref,
                )
                results[row.provider_id] = False
                continue
            weight = DEFAULT_ROW_WEIGHT if row.is_default else NON_DEFAULT_ROW_WEIGHT
            results[row.provider_id] = push_provider_key(
                row.provider_type, value, row_provider_id=row.provider_id, weight=weight,
            )
    if results:
        ok = sum(1 for v in results.values() if v)
        logger.info("Bifrost sync: pushed %d/%d provider keys", ok, len(results))
    return results


def sync_provider_models(
    provider_type: str, model_ids: list[str], row_provider_id: Optional[str] = None,
) -> bool:
    """Update the allow-list on Sentry Agentic's own Bifrost key(s) for
    ``provider_type`` to ``model_ids``. Empty lists are skipped -- wiping
    the allow-list to ``[]`` would cause Bifrost to reject every
    subsequent LLM call for that provider, which we never want just
    because an upstream API had a momentary hiccup.

    Bug fixed 2026-08-06: same root cause as push_provider_key -- this
    tried to GET the provider document and mutate ``keys[0].models`` in
    place, but Bifrost's ``/api/providers/{name}`` endpoint doesn't
    expose or accept a "keys" field at all (confirmed: "keys are not
    accepted on this endpoint; use POST/PUT /api/providers/{provider}/
    keys[/{key_id}] to manage keys"). Now lists our own keys (by name
    prefix -- see _key_name_for_row) via the correct sub-resource and
    PUTs the models list onto each. Only touches keys this module
    created; leaves any other key (e.g. Bifrost's own bootstrap key)
    untouched.

    Bug fixed 2026-08-06 (second one, same day -- live-confirmed via a
    raw GET of /api/providers/anthropic/keys after a "credit balance too
    low" report despite the working key being marked default): when two
    DB rows share a ``provider_type`` (e.g. "Anthropic (default)", an
    exhausted key, and "Sentry", a working one -- both ``provider_type=
    anthropic``), the caller previously unioned every row's models into
    one list and this function pushed that SAME union onto EVERY
    Sentry-Agentic-managed key of that type. That put models the
    exhausted key never actually had access to onto its own allow-list
    too, so Bifrost saw multiple keys all claiming to serve e.g.
    "claude-sonnet-5" and would sometimes route a request to the
    exhausted one regardless of which row the UI had marked default --
    intermittent, not fully fixed by the default-provider bug fix alone.
    ``row_provider_id`` now scopes the PUT to exactly one row's key
    (``_key_name_for_row(row_provider_id)``) so each key's allow-list
    only ever lists models that row's own account actually has. Omitting
    it falls back to the old blanket-apply-to-every-key behavior, kept
    for callers that genuinely want that (e.g. a single-row provider
    type).
    """
    if not provider_type:
        return False
    if not model_ids:
        logger.info(
            "Bifrost sync: skipping empty model list for provider %s "
            "(refusing to wipe allow-list)",
            provider_type,
        )
        return False
    # Normalize + dedupe while preserving order.
    seen: set = set()
    normalized: list[str] = []
    for mid in model_ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        normalized.append(mid)

    with httpx.Client() as client:
        try:
            r = client.get(
                f"{_bifrost_base_url()}/api/providers/{provider_type}/keys",
                timeout=_DEFAULT_TIMEOUT,
            )
            if r.status_code >= 400:
                logger.warning(
                    "Bifrost: GET /api/providers/%s/keys returned %s", provider_type, r.status_code,
                )
                return False
            our_keys = [
                k for k in (r.json().get("keys") or [])
                if isinstance(k.get("name"), str) and k["name"].startswith("sentry-agentic-")
            ]
            if row_provider_id:
                target_name = _key_name_for_row(row_provider_id)
                our_keys = [k for k in our_keys if k.get("name") == target_name]
        except Exception as e:  # noqa: BLE001
            logger.warning("Bifrost: could not list keys for %s: %s", provider_type, e)
            return False

        if not our_keys:
            logger.info(
                "Bifrost sync: no Sentry Agentic-managed key found for provider %s%s yet "
                "(push_provider_key hasn't created one) -- nothing to sync models onto",
                provider_type,
                f" row {row_provider_id}" if row_provider_id else "",
            )
            return False

        all_ok = True
        for k in our_keys:
            try:
                body: Dict[str, Any] = {"name": k["name"], "value": k.get("value"), "models": normalized}
                # Bifrost's PUT is a full replace, not a merge (live-
                # confirmed 2026-08-06: omitting "weight" here silently
                # reset it to 0 on every catalog resync -- which fires on
                # every provider CRUD event via _schedule_catalog_resync,
                # including immediately after set_default_provider had
                # just set it correctly. That's what made the weight fix
                # look like it never took effect: it did, for a few
                # hundred milliseconds, until the next resync clobbered
                # it). Echo the key's own current weight back so a
                # models-only sync never touches it.
                if k.get("weight") is not None:
                    body["weight"] = k["weight"]
                r2 = client.put(
                    f"{_bifrost_base_url()}/api/providers/{provider_type}/keys/{k['id']}",
                    json=body,
                    timeout=_DEFAULT_TIMEOUT,
                )
                if r2.status_code >= 400:
                    logger.warning(
                        "Bifrost: PUT /api/providers/%s/keys/%s (models) returned %s: %s",
                        provider_type, k["id"], r2.status_code, r2.text[:200],
                    )
                    all_ok = False
            except Exception as e:  # noqa: BLE001
                logger.warning("Bifrost: models sync for key %s failed: %s", k.get("name"), e)
                all_ok = False

        if all_ok:
            logger.info(
                "Bifrost: synced %d models onto %d Sentry Agentic-managed key(s) for provider %s",
                len(normalized), len(our_keys), provider_type,
            )
        return all_ok


async def sync_all_provider_models() -> Dict[str, Any]:
    """Canonical refresh for every active LLM provider.

    Single source of truth — called at startup, on a schedule, from the
    refresh endpoints, and lazily on a dropdown cache miss. One call
    does everything:

    1. Fetches each provider's live upstream catalog via
       ``services.provider_model_discovery``.
    2. Applies the configured extras (IDs upstream dropped from
       /v1/models but that still route — e.g. Claude 3.x).
    3. Populates ``_MODEL_LIST_CACHE[provider_id]`` in
       ``services.model_registry`` so the UI dropdown reads the same
       list the sync just computed.
    4. PUTs each row's own model list to that row's own Bifrost key (not
       a union across every row of the same provider_type -- two rows
       sharing a provider_type, e.g. two "anthropic" rows on different
       accounts, must never end up advertising each other's models; see
       ``sync_provider_models``'s 2026-08-06 docstring note for the
       incident that came from unioning here).

    Because all three surfaces (dropdown cache, live-meta cache, Bifrost
    allow-list) are written in the same pass, they cannot drift.

    Concurrent calls are coalesced — if a sync is already running (e.g.
    the scheduled refresher kicked off at the same time as a dropdown
    cold-load), the second caller awaits the same future rather than
    issuing a duplicate round of upstream fetches.

    Best-effort — never raises. Returns a dict with per-provider-type
    Bifrost sync flags under ``bifrost`` and the computed per-row model
    lists under ``models_by_provider`` for observability.
    """
    global _sync_in_flight
    if _sync_in_flight is not None and not _sync_in_flight.done():
        logger.debug("sync_all_provider_models: joining in-flight sync")
        return await _sync_in_flight

    loop = asyncio.get_running_loop()
    _sync_in_flight = loop.create_future()
    try:
        result = await _do_sync_all_provider_models()
        _sync_in_flight.set_result(result)
        return result
    except Exception as exc:
        _sync_in_flight.set_exception(exc)
        raise
    finally:
        # Release the slot so the next scheduled tick or CRUD event can
        # start a fresh sync.
        _sync_in_flight = None


async def _do_sync_all_provider_models() -> Dict[str, Any]:
    # Deferred imports to keep module load cheap.
    from database.connection import get_db_manager
    from database.models import LLMProviderConfig
    from services import provider_model_discovery as discovery
    from services.model_registry import (
        _FALLBACK_MODELS_BY_PROVIDER,
        _MODEL_LIST_CACHE,
        _register_extras,
        get_extra_model_ids,
        record_live_meta,
    )

    db_manager = get_db_manager()
    if db_manager._engine is None:
        db_manager.initialize()

    # Group active providers by type and collect the rows we need to
    # fetch (we don't hold the session open across awaits).
    rows_by_type: Dict[str, list] = {}
    with db_manager.session_scope() as session:
        rows = (
            session.query(LLMProviderConfig)
            .filter(
                LLMProviderConfig.is_active.is_(True),
            )
            .all()
        )
        for row in rows:
            # Detach enough state from the row so we can use it after the
            # session closes. The ORM row becomes unusable post-scope.
            rows_by_type.setdefault(row.provider_type, []).append(
                {
                    "provider_id": row.provider_id,
                    "provider_type": row.provider_type,
                    "base_url": row.base_url,
                    "api_key_ref": row.api_key_ref,
                    "config": dict(row.config or {}),
                }
            )

    bifrost_results: Dict[str, bool] = {}
    per_row_models: Dict[str, List[str]] = {}

    for provider_type, provider_rows in rows_by_type.items():
        # Extras are per-provider-type; apply to every row of this type.
        extras = get_extra_model_ids(provider_type)
        _register_extras(provider_type, extras)

        for row_dict in provider_rows:
            row_ids: List[str] = []
            row_seen: set = set()
            upstream_ok = False

            try:
                meta = await _fetch_meta_for_row(row_dict, discovery)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sync_all_provider_models: discovery failed for %s (%s): %s",
                    row_dict["provider_id"],
                    provider_type,
                    exc,
                )
                meta = None

            if meta is not None:
                upstream_ok = True
                record_live_meta(provider_type, meta)
                for m in meta:
                    if m.id in row_seen:
                        continue
                    row_seen.add(m.id)
                    row_ids.append(m.id)

            # Upstream failed: union the bootstrap list so the dropdown
            # isn't empty while still carrying the extras below.
            if not upstream_ok:
                for mid in _FALLBACK_MODELS_BY_PROVIDER.get(provider_type, ()):
                    if mid not in row_seen:
                        row_seen.add(mid)
                        row_ids.append(mid)

            # Extras are unioned into the row list so the dropdown shows
            # them and the Bifrost allow-list contains them — same list,
            # same source.
            for mid in extras:
                if mid not in row_seen:
                    row_seen.add(mid)
                    row_ids.append(mid)

            # Single-writer: populate the dropdown cache with this row's
            # list. ``fetch_provider_models`` reads this same key.
            _MODEL_LIST_CACHE.set(row_dict["provider_id"], row_ids)
            per_row_models[row_dict["provider_id"]] = row_ids

            # Push straight to THIS row's own Bifrost key -- never union
            # across rows of the same provider_type first (see
            # sync_provider_models' 2026-08-06 docstring note: unioning
            # here is what let an exhausted key's allow-list claim models
            # it never actually had, so Bifrost would sometimes route a
            # request to it regardless of which row the UI marked
            # default).
            if not row_ids:
                # Preserve bootstrap: don't overwrite this key's allow-list
                # with an empty list if this row's discovery failed and
                # there were no extras or fallback either.
                bifrost_results[row_dict["provider_id"]] = False
                continue

            bifrost_results[row_dict["provider_id"]] = sync_provider_models(
                provider_type, row_ids, row_provider_id=row_dict["provider_id"],
            )

    if bifrost_results:
        ok = sum(1 for v in bifrost_results.values() if v)
        logger.info(
            "Model catalog sync: pushed model lists for %d/%d provider rows",
            ok,
            len(bifrost_results),
        )

    return {
        "bifrost": bifrost_results,
        "models_by_provider": per_row_models,
    }


async def _fetch_meta_for_row(row_dict: Dict[str, Any], discovery) -> Optional[list]:
    """Call the appropriate discovery function for one provider row.

    Returns ``None`` when the row isn't usable (e.g. no API key). The
    caller logs and skips.
    """
    from backend.secrets_manager import get_secret

    provider_type = row_dict["provider_type"]
    base_url = row_dict.get("base_url")
    api_key_ref = row_dict.get("api_key_ref")
    config = row_dict.get("config") or {}

    def _resolve_key() -> Optional[str]:
        if api_key_ref:
            try:
                val = get_secret(api_key_ref)
                if val:
                    return val
            except Exception as exc:  # noqa: BLE001
                logger.debug("secret lookup for %s failed: %s", api_key_ref, exc)
        if provider_type == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if provider_type == "openai":
            return os.getenv("OPENAI_API_KEY")
        return None

    if provider_type == "anthropic":
        key = _resolve_key()
        if not key:
            logger.info(
                "Bifrost sync: no Anthropic key available for %s — skipping",
                row_dict["provider_id"],
            )
            return None
        return await discovery.fetch_anthropic_models(key, base_url=base_url)

    if provider_type == "openai":
        key = _resolve_key()
        if not key:
            logger.info(
                "Bifrost sync: no OpenAI key available for %s — skipping",
                row_dict["provider_id"],
            )
            return None
        return await discovery.fetch_openai_models(
            key,
            base_url=base_url,
            organization=config.get("organization"),
        )

    if provider_type == "ollama":
        return await discovery.fetch_ollama_models(base_url)

    logger.debug("Bifrost sync: unsupported provider_type %s", provider_type)
    return None
