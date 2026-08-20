"""Shared LLM synthesis helper for Phase 3 capabilities.

Every specialist capability needs the same thing: a fast, stateless,
highest-priority single-shot reasoning call over already-retrieved,
grounded evidence. Factored out here so the fix below only has to exist
once.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def synthesize(
    prompt: str, *, agent_id: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Returns (text, error) -- never raises. Unwraps the LLM gateway's
    actual, live-verified return shape: submit_triage's own type hint says
    Optional[str], but it actually returns a content-block dict
    ({'content': ..., 'type': 'text'}) -- live validation of the Triage
    capability (Milestone 1) caught this as a real bug (the raw dict was
    being stringified into the output instead of its text extracted).
    Handle both shapes rather than trust the hint.

    ``agent_id`` should be one of the canonical keys from
    ``services/soc_agents.py``'s AGENTS dict (e.g. "triage", "investigator",
    "threat_intel", "reporter") so this call attributes correctly in
    LLMInteractionLog's per-agent cost/token breakdown -- background
    capability calls previously logged with agent_id=NULL since
    submit_triage() didn't accept one."""
    from services.llm_gateway import get_llm_gateway

    try:
        gateway = await get_llm_gateway()
        raw_response = await gateway.submit_triage(prompt, agent_id=agent_id)
    except Exception as e:  # noqa: BLE001
        logger.error("Capability synthesis call failed: %s", e, exc_info=True)
        return None, f"synthesis call failed: {e}"

    text = raw_response.get("content") if isinstance(raw_response, dict) else raw_response

    if not text:
        return None, "synthesis returned no response"
    return text, None


def split_sections(response_text: str, marker: str) -> str:
    """Return the text after `marker` (e.g. 'ASSESSMENT:'), stripped of
    leading markdown bold asterisks left over from the split. Returns the
    full text unchanged if the marker isn't present."""
    if marker not in response_text:
        return response_text
    return response_text.split(marker, 1)[1].strip().lstrip("*").strip()
