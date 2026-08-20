"""Triage capability (Phase 3, Milestone 1 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Given a threat/alert, composes threat_detail (severity, verdict,
classification, response actions taken, analyst attribution -- enriched in
Milestone 9) and, when the alert carries a storylineId, storyline_pivot
(blast radius), then synthesizes a grounded verdict via Claude.

Deliberately bespoke Python rather than a generic plan-list executor: the
storyline_pivot step is conditional on threat_detail's own result (only
runs if a storylineId was found), which the Milestone 0 runner's static
plan format doesn't express. This mirrors why services/
sentinelone_recipe_executor.py itself is bespoke functions rather than a
generic YAML interpreter -- real per-capability logic is the lower-risk
choice, per that module's own documented rationale. Both steps still go
through the same production recipe entry point
(services.sentinelone_recipe_executor.execute) -- never a raw MCP tool
call, preserving the brief's composition-only rule exactly as the runner
enforces it for static plans.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TriageOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    evidence: list[str] = field(default_factory=list)
    assessment: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None


_SYNTHESIS_INSTRUCTIONS = """You are the Triage capability of a SOC agent. You are given retrieved, grounded evidence about one SentinelOne alert -- never invent facts beyond what is stated below.

Be brief and strategic: no filler, no restating the question, no generic caveats beyond what's specifically true here. Target well under 150 words total.

Produce your answer as exactly two sections:

EVIDENCE:
(What occurred -- 1-2 sentences restating only the retrieved facts given below, in plain language. No judgement here.)

ASSESSMENT:
Verdict: <true positive | false positive | uncertain>
Severity confirmation: <restate the retrieved severity; explicitly flag if anything in the evidence conflicts with it>
Blast radius: <the storyline alert count if given below; otherwise state plainly that blast radius could not be estimated because this alert has no storyline -- never guess a number>
Confidence: <0-100>
Reasoning: <1-3 sentences on WHY this verdict follows from the evidence -- the problem this alert represents, not just a restatement. If the evidence already contains a human analyst's recorded verdict, treat it as the strongest signal and say so explicitly rather than silently overriding it.>
Source: <name exactly what this is grounded in, e.g. "SentinelOne alert detail + storyline pivot">

Retrieved evidence:
{evidence}
"""


async def run_triage(alert_id: str) -> TriageOutcome:
    """Execute the Triage capability end to end for one alert_id."""
    from services import sentinelone_recipe_executor as executor

    detail_outcome = await executor.execute("threat_detail", f"tell me more about alert {alert_id}")
    if detail_outcome.kind == "execution_error":
        return TriageOutcome(kind="execution_error", error=detail_outcome.error)
    if detail_outcome.kind == "needs_clarification":
        return TriageOutcome(kind="needs_clarification", clarifying_question=detail_outcome.clarifying_question)

    evidence = [detail_outcome.answer] if detail_outcome.answer else []
    raw = detail_outcome.raw_data or {}
    storyline_id = raw.get("storyline_id")

    if storyline_id:
        storyline_outcome = await executor.execute(
            "storyline_pivot", f"reconstruct the attack chain for storyline {storyline_id}"
        )
        if storyline_outcome.kind == "answered" and storyline_outcome.answer:
            evidence.append(storyline_outcome.answer)
        # A storyline-pivot failure doesn't invalidate the alert detail
        # already retrieved -- Triage proceeds with what it has, and the
        # synthesis instructions already tell the model to say plainly
        # when blast radius couldn't be estimated.

    if not evidence:
        return TriageOutcome(
            kind="execution_error",
            error="no evidence could be retrieved for this alert -- refusing to synthesize a verdict from nothing",
        )

    prompt = _SYNTHESIS_INSTRUCTIONS.format(evidence="\n\n".join(evidence))

    from capabilities.synthesis import split_sections, synthesize

    response_text, err = await synthesize(prompt, agent_id="triage")
    if err:
        return TriageOutcome(kind="execution_error", evidence=evidence, error=err)

    assessment = split_sections(response_text, "ASSESSMENT:")
    return TriageOutcome(kind="answered", evidence=evidence, assessment=assessment)
