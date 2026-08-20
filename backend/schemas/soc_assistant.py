"""Pydantic schemas for the SOC Assistant integration.

The counterparty is an external shift-management dashboard that proxies
every request server-side (never from an analyst's browser) so `email`
below is a trustworthy, pre-authenticated identity, not user input to
validate against. See `backend/api/soc_assistant.py` for the router and
the full contract this implements.

This file is deliberately the single home for every SOC Assistant request/
response model -- the contract covers 6 endpoints total (chat is the only
one implemented so far); new models for the data-vault, incident-report,
knowledge-ingest, and automation draft/pull endpoints belong here too when
built, so the whole integration's wire shapes stay in one place.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SocAssistantChatTurn(BaseModel):
    """One prior turn in a conversation thread, as the dashboard stores it."""

    role: str  # "user" | "assistant"
    content: str

    @field_validator("role")
    @classmethod
    def _role_valid(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError('role must be "user" or "assistant"')
        return v


class SocAssistantChatRequest(BaseModel):
    """`POST /api/chat` request body, per the contract."""

    message: str
    email: str
    # Optional: omitted entirely on the first message of a thread, or when
    # the admin sets the history-turns setting to 0. Oldest-first, does not
    # include the current `message`.
    history: Optional[List[SocAssistantChatTurn]] = None
    # Optional (added 2026-08-12): which client this question concerns, if
    # the dashboard knows -- looked up against services/client_registry_
    # service.py's EDR (SentinelOne) / SIEM (AlienVault Central) detection
    # so the agent can ground its answer in what platform(s) that client
    # actually has, rather than assuming. Free text, matched by name
    # (exact, then normalized) -- an unrecognized name is not an error,
    # it's just not grounded with extra context.
    client: Optional[str] = None

    @field_validator("message")
    @classmethod
    def _message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v

    @field_validator("email")
    @classmethod
    def _email_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("email must not be empty")
        return v
