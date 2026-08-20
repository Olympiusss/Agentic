"""Investigator capability (Phase 3, Milestone 2 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Given an entry-point alert, composes threat_detail (to find its
storylineId) and storyline_pivot (the full chain of alerts sharing that
storyline) to reconstruct a timeline and affected-host list, then asks
Claude to suggest likely MITRE tactics/techniques from the alerts' own
names/descriptions -- labeled explicitly as interpretation, since
SentinelOne's Alert entity carries no structured MITRE field in this
integration (confirmed Milestone 9's full tool-inventory scan).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class InvestigatorOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    evidence: list[str] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    affected_hosts: list[str] = field(default_factory=list)
    assessment: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None


_SYNTHESIS_INSTRUCTIONS = """You are the Investigator capability of a SOC agent. You are given a retrieved, grounded attack-chain timeline for one SentinelOne storyline -- never invent an alert, host, or technique not present in the evidence below.

Be brief and strategic: no filler, no restating the question, no generic caveats beyond what's specifically true here. Target well under 150 words total.

Produce your answer as exactly two sections:

EVIDENCE:
(What occurred -- restate the timeline and affected hosts given below, verbatim in substance. No MITRE mapping or narrative here.)

ASSESSMENT:
Likely MITRE tactics/techniques: <infer from the alerts' own names/descriptions below -- this tenant's SentinelOne integration carries no structured MITRE field, so state clearly that this is inference from naming patterns, not retrieved data. If nothing in the names suggests a specific technique, say so rather than guessing one.>
Narrative: <1-3 sentences on how the chain likely unfolded and WHY it matters -- the problem it represents for this environment -- explicitly marked as interpretation>
Source: <name exactly what this is grounded in, e.g. "storyline_pivot timeline, N alerts across M hosts">

Retrieved timeline (chronological):
{timeline}

Affected hosts: {hosts}
"""


async def run_investigator(alert_id: str) -> InvestigatorOutcome:
    """Execute the Investigator capability end to end for one entry-point alert_id."""
    from services import sentinelone_recipe_executor as executor

    detail_outcome = await executor.execute("threat_detail", f"tell me more about alert {alert_id}")
    if detail_outcome.kind == "execution_error":
        return InvestigatorOutcome(kind="execution_error", error=detail_outcome.error)
    if detail_outcome.kind == "needs_clarification":
        return InvestigatorOutcome(kind="needs_clarification", clarifying_question=detail_outcome.clarifying_question)

    evidence = [detail_outcome.answer] if detail_outcome.answer else []
    raw = detail_outcome.raw_data or {}
    storyline_id = raw.get("storyline_id")

    if not storyline_id:
        return InvestigatorOutcome(
            kind="answered",
            evidence=evidence,
            assessment=(
                "EVIDENCE: this alert carries no storylineId, so there is no broader attack "
                "chain to reconstruct -- it stands alone.\n\nASSESSMENT: no chain-level MITRE "
                "mapping or narrative is possible without a storyline to reason over. For "
                "hash/process-level detail on this specific alert, ask Athena <Threat Intel> "
                "to analyze its artifacts instead -- that pulls from Deep Visibility directly, "
                "not the storyline timeline this capability reasons over."
            ),
        )

    storyline_outcome = await executor.execute(
        "storyline_pivot", f"reconstruct the attack chain for storyline {storyline_id}"
    )
    if storyline_outcome.kind == "execution_error":
        return InvestigatorOutcome(kind="execution_error", evidence=evidence, error=storyline_outcome.error)
    if storyline_outcome.answer:
        evidence.append(storyline_outcome.answer)

    chain = (storyline_outcome.raw_data or {}).get("chain", [])
    timeline = sorted(
        (
            {
                "detected_at": c.get("detected_at"),
                "name": c.get("name"),
                "severity": c.get("severity"),
                "host": (c.get("asset") or {}).get("name"),
            }
            for c in chain
        ),
        key=lambda t: t["detected_at"] or "",
    )
    affected_hosts = sorted({t["host"] for t in timeline if t["host"]})

    if not timeline:
        return InvestigatorOutcome(
            kind="answered",
            evidence=evidence,
            assessment=(
                f"EVIDENCE: storyline {storyline_id} returned no other correlated alert-chain "
                "events -- either this genuinely was an isolated detection with nothing else on "
                "the same storyline, or the underlying telemetry has since aged out of retention "
                "(this can happen on older/resolved alerts).\n\nASSESSMENT: no attack-chain "
                "narrative can be built from zero events -- this isn't a failure to find "
                "something that's there, there is nothing else recorded on this storyline right "
                "now. Ask Athena <Threat Intel> for hash/process/signed-binary analysis on this "
                "alert directly -- Deep Visibility artifact data is a separate query from this "
                "storyline-timeline reconstruction and may still be available."
            ),
        )

    timeline_text = "\n".join(f"- {t['detected_at']}: {t['name']} (severity={t['severity']}, host={t['host']})" for t in timeline)
    prompt = _SYNTHESIS_INSTRUCTIONS.format(timeline=timeline_text, hosts=", ".join(affected_hosts) or "none identified")

    from capabilities.synthesis import split_sections, synthesize

    response_text, err = await synthesize(prompt, agent_id="investigator")
    if err:
        return InvestigatorOutcome(
            kind="execution_error", evidence=evidence, timeline=timeline, affected_hosts=affected_hosts, error=err
        )

    assessment = split_sections(response_text, "ASSESSMENT:")
    return InvestigatorOutcome(
        kind="answered",
        evidence=evidence,
        timeline=timeline,
        affected_hosts=affected_hosts,
        assessment=assessment,
    )
