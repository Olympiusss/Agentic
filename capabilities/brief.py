"""Resident 24-hour brief capability (Phase 3, Milestone 7 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Composes incident_status (severity/status movement), endpoint_count, and
agent_health into one grounded, per-tenant brief. This is scheduled
reporting -- an intelligence output. It recommends nothing be actioned and
takes no action itself, per the brief's own explicit distinction from
Objective 2 (autonomous action/Responder).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BriefOutcome:
    kind: str  # "answered" | "execution_error"
    evidence: list[str] = field(default_factory=list)
    summary: Optional[str] = None
    generated_at: Optional[str] = None
    error: Optional[str] = None


_SYNTHESIS_INSTRUCTIONS = """You are the Reporter capability of a SOC agent, generating a resident 24-hour brief. You are given retrieved, grounded evidence -- never invent a fact not present below. This is reporting only: never recommend or imply that any action was taken by you, only what a human analyst might consider.

Produce your answer as exactly two sections:

EVIDENCE:
(Restate the retrieved incident status, endpoint count, and agent-health facts below, verbatim in substance.)

ASSESSMENT:
Summary: <one paragraph suitable for starting a shift with -- notable detections, any agent-health concerns, explicitly marked as interpretation where you're characterizing a trend rather than restating a retrieved number>

Retrieved evidence:
{evidence}
"""


async def run_brief(window_hours: int = 24) -> BriefOutcome:
    from services import sentinelone_recipe_executor as executor

    evidence: list[str] = []
    for question_class, question in [
        ("incident_status", "what's our incident status breakdown"),
        ("endpoint_count", "how many endpoints do we have in total"),
        ("agent_health", "which agents are offline"),
    ]:
        outcome = await executor.execute(question_class, question)
        if outcome.kind == "execution_error":
            return BriefOutcome(kind="execution_error", evidence=evidence, error=f"{question_class} failed: {outcome.error}")
        if outcome.answer:
            evidence.append(outcome.answer)

    if not evidence:
        return BriefOutcome(kind="execution_error", error="no evidence could be retrieved for this brief")

    prompt = _SYNTHESIS_INSTRUCTIONS.format(evidence="\n\n".join(evidence))

    from capabilities.synthesis import split_sections, synthesize

    response_text, err = await synthesize(prompt, agent_id="reporter")
    if err:
        return BriefOutcome(kind="execution_error", evidence=evidence, error=err)

    summary = split_sections(response_text, "ASSESSMENT:")
    generated_at = datetime.now(timezone.utc).isoformat()
    return BriefOutcome(kind="answered", evidence=evidence, summary=summary, generated_at=generated_at)
