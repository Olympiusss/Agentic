"""SOC Assistant integration API.

Backend contract for an external shift-management dashboard: it proxies
every request server-side (never from an analyst's browser), so the
`email` field on each request is a trustworthy, pre-authenticated staff
identity, not something to validate against our own user table. The
dashboard's admin configures our base URL + this endpoint's bearer key
under their System -> SOC Assistant settings.

Endpoints:
  - POST /chat   Streaming chat -- an analyst's investigative question,
                 dispatched through Zeus (Master Orchestrator) so this
                 integration gets the same subagent-routing behavior a
                 human gets picking Zeus in the chat drawer's dropdown.

Inbound auth is a Bearer API key stored via the secrets manager under
`SOC_ASSISTANT_API_KEY` -- same pattern as `backend/api/vstrike.py`'s
`verify_inbound_key`. When `DEV_MODE=true` the auth check is bypassed
(matches the rest of the Sentry Agentic codebase).

This file is the intended home for the rest of the SOC Assistant contract
(data-vault log captures, incident-report drafts, knowledge ingest, and
the automation draft/pull-ticket pair) when those get built -- they should
reuse `verify_soc_assistant_key` and `_rate_limit` below rather than
inventing new auth/throttling per endpoint.
"""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas.soc_assistant import SocAssistantChatRequest
from core.rate_limit import get_bucket
from services.claude_service import ClaudeService

router = APIRouter()
logger = logging.getLogger(__name__)

# Zeus, the Master Orchestrator (services/soc_agents.py) -- "presides over
# Olympiuss, Venus, Orion, Ariadne, Athena, and Hermes." Defaulting every
# SOC Assistant chat request to this agent_id gives the external caller
# the same subagent-routing a human gets by picking Zeus in the chat
# drawer's dropdown, matching the integration's stated goal ("leverage our
# chat interface, our subagents function").
_ZEUS_AGENT_ID = "auto_responder"


def _is_dev_mode() -> bool:
    return os.environ.get("DEV_MODE", "").lower() == "true"


def _expected_api_key() -> Optional[str]:
    """Return the expected inbound bearer key, or None if unset."""
    key = os.environ.get("SOC_ASSISTANT_API_KEY")
    if key:
        return key
    try:
        from backend.secrets_manager import get_secret

        return get_secret("SOC_ASSISTANT_API_KEY")
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read SOC_ASSISTANT_API_KEY from secrets: %s", e)
        return None


def verify_soc_assistant_key(
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Bearer-token dependency for every SOC Assistant endpoint.

    Bypassed when `DEV_MODE=true`. Returns 401 when the header is missing
    or the token doesn't match, 503 if no key is configured and DEV_MODE
    is off -- we refuse to run open on a route reachable from outside
    this deployment (see backend/api/vstrike.py's identical rule).
    """
    if _is_dev_mode():
        return

    expected = _expected_api_key()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SOC Assistant API key not configured. Set SOC_ASSISTANT_API_KEY or enable DEV_MODE.",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


async def _rate_limit() -> None:
    """Shared token bucket across every SOC Assistant call.

    One bucket, not per-IP: the contract guarantees a single calling host
    (the dashboard server), so there's nothing to key per-caller on.
    """
    bucket = get_bucket("soc_assistant", capacity=30, refill_rate=0.5)
    if not await bucket.acquire():
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


@router.post("/chat")
async def soc_assistant_chat(
    request: SocAssistantChatRequest,
    _auth: None = Depends(verify_soc_assistant_key),
    _rl: None = Depends(_rate_limit),
):
    """Streaming chat for the shift-management dashboard.

    Request/response shape is the counterparty's contract, not our own
    internal `/api/claude/chat/stream` format: plain `message`/`email`/
    `history` in, a raw chunked text body out (no SSE envelope, no JSON) --
    the dashboard reads the body as it arrives and shows it live.

    Each call is treated as fully stateless server-side: `history` (oldest
    first, not including `message`) is the only source of prior turns we
    use. We never assume our own session continuity, so our own
    context-summarization logic can't drift from what the dashboard's own
    stored thread believes happened.
    """
    from backend.api.claude import _resolve_model_for_request

    logger.info(
        "SOC Assistant chat request: email=%s history_turns=%d client=%s",
        request.email,
        len(request.history or []),
        request.client or "-",
    )

    claude_service = ClaudeService(use_backend_tools=True)
    if not claude_service.has_api_key():
        raise HTTPException(
            status_code=503,
            detail="No Anthropic LLM provider is configured.",
        )

    model = _resolve_model_for_request(None, _ZEUS_AGENT_ID)
    context = (
        [{"role": turn.role, "content": turn.content} for turn in request.history]
        if request.history
        else None
    )

    # Client-awareness (2026-08-12): ground the question in what platform(s)
    # the named client actually has, rather than letting the agent assume.
    # Prepended straight into the message text -- same technique `context`/
    # `history` already use to feed Claude more input, not a ClaudeService
    # architecture change. An unrecognized client name degrades silently
    # (no note added), it is never treated as an error on this contract.
    outbound_message = request.message
    if request.client:
        from services.client_registry_service import find_client

        record = find_client(request.client)
        if record is not None:
            if record.has_edr and record.has_siem:
                coverage = "EDR (SentinelOne) and SIEM (AlienVault Central)"
            elif record.has_edr:
                coverage = "EDR (SentinelOne) only -- no SIEM/AlienVault coverage"
            else:
                coverage = "SIEM (AlienVault Central) only -- no EDR/SentinelOne coverage"
            outbound_message = (
                f"[Client context: '{record.name}' has {coverage}. If asked about a "
                f"platform this client doesn't have, say so plainly rather than "
                f"guessing.]\n\n{request.message}"
            )

    async def generate() -> AsyncIterator[str]:
        try:
            async for chunk in claude_service.chat_stream(
                message=outbound_message,
                context=context,
                model=model,
                agent_id=_ZEUS_AGENT_ID,
            ):
                if isinstance(chunk, dict):
                    if chunk.get("type") == "text":
                        content = chunk.get("content") or ""
                        if content:
                            yield content
                    # Every other event type (thinking, thinking_start/end,
                    # context_summarized, usage, ...) is internal-only --
                    # the contract wants a plain answer-token stream, not
                    # our own event model.
                else:
                    # Legacy plain-string chunk format.
                    yield str(chunk)
        except Exception as e:  # noqa: BLE001
            logger.error("SOC Assistant chat stream error (email=%s): %s", request.email, e, exc_info=True)
            # No structured error channel in this contract (raw text body,
            # no JSON envelope) -- surface it inline so the dashboard shows
            # *something* rather than an abruptly-truncated stream.
            yield f"\n[error: {e}]\n"

    return StreamingResponse(generate(), media_type="text/plain")
