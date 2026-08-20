"""Correlator capability (Phase 3, Milestone 4 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Fetches a bounded sample of recent alerts (via the same search_alerts tool
threat_count already uses, through the recipe executor's own _call
helper -- same reasoning as Hunter's direct powerquery calls: still going
through the established, tested calling convention, not a raw ad-hoc MCP
call), clusters them by shared storylineId, shared host, or shared
classification across multiple hosts, and asks Claude to flag any
multi-host pattern as a possible campaign -- explicitly labeled as
interpretation, never presented as a retrieved fact.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Cluster:
    kind: str  # "storyline" | "host" | "classification_multi_host"
    key: str
    alert_ids: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)


@dataclass
class CorrelatorOutcome:
    kind: str  # "answered" | "execution_error"
    clusters: list[Cluster] = field(default_factory=list)
    sample_size: int = 0
    assessment: Optional[str] = None
    error: Optional[str] = None


_SYNTHESIS_INSTRUCTIONS = """You are the Correlator capability of a SOC agent. You are given retrieved, grounded alert clusters from a recent sample -- never invent a cluster or host not present below.

Be brief and strategic: no filler, no restating the question, no generic caveats beyond what's specifically true here. Target well under 150 words total.

Produce your answer as exactly two sections:

EVIDENCE:
(What occurred -- restate the clusters given below, verbatim in substance. No hypothesis here.)

ASSESSMENT:
Campaign hypothesis: <ONLY if a cluster spans multiple distinct hosts under the same classification/pattern, describe the possible campaign and WHY it matters (the risk it represents), explicitly marked as interpretation. If every cluster is confined to a single host, state plainly that no cross-host campaign pattern is evident in this sample -- a single host's own repeated alerts are not a campaign.>
Source: <name exactly what this is grounded in, e.g. "search_alerts sample of N recent alerts">

Retrieved clusters:
{clusters}
"""


async def run_correlator(sample_size: int = 50) -> CorrelatorOutcome:
    from services import sentinelone_recipe_executor as executor

    result, err = await executor._call("list_alerts", {"first": min(sample_size, 100), "view_type": "ALL"})
    if err:
        return CorrelatorOutcome(kind="execution_error", error=err)
    rows = executor._edges(result)
    if not rows:
        return CorrelatorOutcome(kind="answered", sample_size=0, assessment="No alerts were returned to correlate.")

    by_storyline: dict[str, list[dict]] = defaultdict(list)
    by_host: dict[str, list[dict]] = defaultdict(list)
    by_classification: dict[str, set[str]] = defaultdict(set)
    by_classification_alerts: dict[str, list[dict]] = defaultdict(list)

    for r in rows:
        host = (r.get("asset") or {}).get("name")
        storyline_id = r.get("storylineId")
        classification = r.get("classification")
        if storyline_id:
            by_storyline[storyline_id].append(r)
        if host:
            by_host[host].append(r)
        if classification and host:
            by_classification[classification].add(host)
            by_classification_alerts[classification].append(r)

    clusters: list[Cluster] = []
    for sid, alerts in by_storyline.items():
        if len(alerts) > 1:
            clusters.append(
                Cluster(kind="storyline", key=sid, alert_ids=[a.get("id") for a in alerts],
                        hosts=sorted({(a.get("asset") or {}).get("name") for a in alerts if a.get("asset")}))
            )
    for host, alerts in by_host.items():
        if len(alerts) > 1:
            clusters.append(Cluster(kind="host", key=host, alert_ids=[a.get("id") for a in alerts], hosts=[host]))
    for classification, hosts in by_classification.items():
        if len(hosts) > 1:
            alerts = by_classification_alerts[classification]
            clusters.append(
                Cluster(kind="classification_multi_host", key=classification,
                        alert_ids=[a.get("id") for a in alerts], hosts=sorted(hosts))
            )

    if not clusters:
        return CorrelatorOutcome(
            kind="answered", sample_size=len(rows),
            assessment="EVIDENCE: no repeated storyline, host, or cross-host classification pattern found in this sample.\n\nASSESSMENT: no campaign hypothesis -- nothing to correlate.",
        )

    clusters_text = "\n".join(
        f"- [{c.kind}] {c.key}: {len(c.alert_ids)} alert(s) across host(s) {', '.join(c.hosts) or 'unknown'}"
        for c in clusters
    )
    prompt = _SYNTHESIS_INSTRUCTIONS.format(clusters=clusters_text)

    from capabilities.synthesis import split_sections, synthesize

    response_text, synth_err = await synthesize(prompt, agent_id="correlator")
    if synth_err:
        return CorrelatorOutcome(kind="execution_error", clusters=clusters, sample_size=len(rows), error=synth_err)

    assessment = split_sections(response_text, "ASSESSMENT:")
    return CorrelatorOutcome(kind="answered", clusters=clusters, sample_size=len(rows), assessment=assessment)
