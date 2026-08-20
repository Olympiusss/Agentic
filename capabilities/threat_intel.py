"""Threat Intel capability (Phase 3, Milestone 5 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Enriches a CVE indicator: the keyless CVE database (cve_search_by_id, no
API key required) for CVSS/references, plus cve_traversal for which of our
own assets are affected. Hash-reputation enrichment (the brief's other
suggested source) is NOT composed here -- VirusTotal/GTI's threat_intel_*
tools require PURPLEMCP_VT_API_KEY, confirmed not configured in this
tenant (data/knowledge/sentinelone/mcp_tools.md). Rather than silently
drop that half of "Threat Intel," this capability states the limitation
explicitly when relevant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

HASH_REPUTATION_UNAVAILABLE_NOTE = (
    "Hash-reputation enrichment (VirusTotal/GTI) is not available in this tenant -- "
    "PURPLEMCP_VT_API_KEY is not configured. CVE-based enrichment below is not a "
    "substitute for a file-hash lookup."
)


@dataclass
class ThreatIntelOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    evidence: list[str] = field(default_factory=list)
    assessment: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None


_SYNTHESIS_INSTRUCTIONS = """You are the Threat Intel capability of a SOC agent. You are given retrieved, grounded evidence about one CVE -- never invent a fact not present below.

Be brief and strategic: no filler, no restating the question, no generic caveats beyond what's specifically true here. Target well under 150 words total.

Produce your answer as exactly two sections:

EVIDENCE:
(What occurred -- restate the retrieved CVE detail and asset-exposure facts below, verbatim in substance. No judgement here.)

ASSESSMENT:
Reputation/severity: <from the CVE's own CVSS score and severity, stated as fact -- sourced, not inferred>
Technique context: <ONLY if the CVE's own description implies a specific attack technique -- explicitly marked as interpretation. If nothing in the description implies one, say so rather than guessing.>
Why it matters: <1-2 sentences on the concrete risk this represents for this tenant's environment, grounded strictly in the asset-exposure evidence below -- not a generic CVE-severity restatement>
Attribution: <state plainly that no threat-actor attribution source exists in this integration -- never invent one>
Source: <name exactly what this is grounded in, e.g. "cve_search_by_id + cve_traversal">

Retrieved evidence:
{evidence}
"""


def _extract_cve_facts(cve_detail: dict) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """cve_search_by_id returns a real CVE Record Format 5.2 document
    (live-verified, not the flat {'description', 'cvss'} shape an earlier
    version of this function assumed) -- description lives at
    containers.cna.descriptions[0].value, and CVSS lives under
    containers.adp[*].metrics[*], keyed by whichever version the assigner
    used (cvssV3_1, cvssV3_0, cvssV2_0) -- there is no single fixed key.
    Defensive throughout: CVE records vary in completeness."""
    containers = cve_detail.get("containers", {}) if isinstance(cve_detail, dict) else {}
    cna = containers.get("cna", {}) if isinstance(containers, dict) else {}
    descriptions = cna.get("descriptions", []) if isinstance(cna, dict) else []
    description = descriptions[0].get("value") if descriptions and isinstance(descriptions[0], dict) else None

    base_score, base_severity = None, None
    for adp in containers.get("adp", []) if isinstance(containers, dict) else []:
        for metric in adp.get("metrics", []) if isinstance(adp, dict) else []:
            for key, value in metric.items():
                if key.lower().startswith("cvssv") and isinstance(value, dict):
                    base_score = value.get("baseScore", base_score)
                    base_severity = value.get("baseSeverity", base_severity)
    return description, base_score, base_severity


async def run_threat_intel(cve_id: str) -> ThreatIntelOutcome:
    from services import sentinelone_recipe_executor as executor

    evidence: list[str] = []

    cve_detail, err = await executor._call("cve_search_by_id", {"cve_id": cve_id})
    if err:
        return ThreatIntelOutcome(kind="execution_error", error=f"cve_search_by_id failed: {err}")
    if isinstance(cve_detail, dict) and cve_detail:
        description, base_score, base_severity = _extract_cve_facts(cve_detail)
        evidence.append(
            f"CVE database record for {cve_id}: {(description or 'no description available')[:500]} "
            f"(CVSS base score: {base_score if base_score is not None else 'not available'}, "
            f"severity: {base_severity or 'not available'})."
        )
    else:
        evidence.append(f"No CVE database record found for {cve_id}.")

    traversal_outcome = await executor.execute("cve_traversal", f"is {cve_id} present in our environment")
    if traversal_outcome.kind == "execution_error":
        return ThreatIntelOutcome(kind="execution_error", evidence=evidence, error=traversal_outcome.error)
    if traversal_outcome.answer:
        evidence.append(traversal_outcome.answer)

    prompt = _SYNTHESIS_INSTRUCTIONS.format(evidence="\n\n".join(evidence))

    from capabilities.synthesis import split_sections, synthesize

    response_text, synth_err = await synthesize(prompt, agent_id="threat_intel")
    if synth_err:
        return ThreatIntelOutcome(kind="execution_error", evidence=evidence, error=synth_err)

    assessment = split_sections(response_text, "ASSESSMENT:")
    return ThreatIntelOutcome(kind="answered", evidence=evidence, assessment=assessment)
