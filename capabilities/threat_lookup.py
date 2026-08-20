"""Threat-lookup capability (explicit user request, 2026-08-05: "we want
to scale our agents' operation from just being accessible from the chat
interface -- every external action must be able to be retrieve[d] via
the interface... these threat details as sent, if i want to query for
insights or even more insights, this and even more should be accessible
via the interface").

capabilities/synergy.py's Zeus pipeline already computes and stores
everything -- Venus's timeline, Athena's artifact/reputation findings,
Orion's hunt status, Ariadne's correlation, Themis's review -- in
Finding.ai_enrichment, and fires an email notification summarizing it.
Until this capability, that record only ever reached the recipient's
inbox; nothing about it was queryable from chat. This closes that gap:
"what threats have you notified me about" and "give me more insight on
<finding>" both read the SAME internal store, surfacing the full
breakdown, not just what fit in the email.

Deliberately reads Sentry Agentic's own internal Finding store (same source
services/strategic_insights_service.py uses for the dashboard), never
SentinelOne directly -- this answers "what did WE already find and tell
you," not a fresh SentinelOne retrieval question, so it doesn't go
through services/sentinelone_recipe_executor.py at all.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_FINDING_ID_RE = re.compile(r"s1-[0-9a-f-]{20,}", re.IGNORECASE)
_STOPWORDS = {
    "give", "tell", "more", "about", "insight", "insights", "detail", "details",
    "threat", "finding", "what", "which", "notified", "notification", "please",
    "recent", "the", "that", "this", "show", "want", "know",
}

# Deliberately simple keyword -> agent map (explicit user request,
# 2026-08-05: "if the further questions asked is not retrievable, it
# should refer the user to the right agent that can act on its query").
# Same "keyword tier, not embedding router" honesty as
# is_threat_lookup_query below -- this is a coarse triage hint for
# Hermes to hand off with, not a claim of precise intent classification.
_REFERRAL_MAP: list[tuple[tuple[str, ...], str]] = [
    (("hunt", "powerquery", "deep visibility", "lolbin", "persistence", "lateral movement"), "Orion <Threat Hunter>"),
    (("cve", "vulnerability", "vulnerabilities", "patch"), "Athena <Threat Intel>"),
    (("investigate", "storyline", "timeline", "attack chain"), "Venus <Investigator>"),
    (("correlate", "correlation", "campaign", "pattern", "cluster"), "Ariadne <Correlator>"),
    (("triage", "prioritize", "prioritise"), "Olympiuss <Triage>"),
    (("isolate", "block", "contain", "take action", "respond"), "Zeus <Master Orchestrator>"),
    (("compliance", "audit the agents", "agent health", "system health"), "Themis <Compliance & Debug>"),
]


def suggest_referral(question: str) -> Optional[str]:
    q = question.lower()
    for keywords, agent_name in _REFERRAL_MAP:
        if any(k in q for k in keywords):
            return agent_name
    return None


@dataclass
class ThreatLookupOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    answer: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None


def is_threat_lookup_query(question: str) -> bool:
    """Deliberately simple keyword match, not an embedding router -- same
    tier of routing as the agent-selected capabilities' own extract_uuid/
    extract_cve_id checks, not the SentinelOne grounding router's
    calibrated embedding classifier (that router answers live SentinelOne
    retrieval questions; this answers questions about our own
    already-computed analysis, a different data source entirely)."""
    q = question.lower()
    return bool(
        re.search(r"\bnotif", q)
        or "recent threat" in q
        or "what threats" in q
        or ("insight" in q and ("threat" in q or "finding" in q or _FINDING_ID_RE.search(question)))
    )


def _extract_finding_id(question: str) -> Optional[str]:
    m = _FINDING_ID_RE.search(question)
    if m:
        return m.group(0)
    from services import sentinelone_entity_extraction as s1_extract

    uid = s1_extract.extract_uuid(question)
    return f"s1-{uid}" if uid else None


async def list_recent_notified_threats(hours: int = 72) -> ThreatLookupOutcome:
    """Every finding whose blackboard carries a 'notification' key --
    i.e. every threat an email/Telegram alert actually went out for --
    within the window, most recent first."""
    from services.database_data_service import DatabaseDataService

    try:
        svc = DatabaseDataService()
        findings = svc.get_findings(data_source="sentinelone", limit=200)
    except Exception as e:  # noqa: BLE001
        return ThreatLookupOutcome(kind="execution_error", error=str(e))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    notified: list[tuple[dict, dict, Optional[datetime]]] = []
    for f in findings:
        notif = (f.get("ai_enrichment") or {}).get("notification")
        if not notif:
            continue
        sent_at = None
        try:
            sent_at = datetime.fromisoformat(str(notif.get("sent_at")).replace("Z", "+00:00"))
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
        if sent_at is not None and sent_at < cutoff:
            continue
        notified.append((f, notif, sent_at))

    if not notified:
        return ThreatLookupOutcome(kind="answered", answer=f"No threats have been notified in the last {hours} hours.")

    notified.sort(key=lambda t: t[2] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    lines = []
    for f, notif, _sent_at in notified[:15]:
        athena = (f.get("ai_enrichment") or {}).get("athena_threat_intel") or {}
        hosts = (f.get("entity_context") or {}).get("hostnames") or []
        lines.append(
            f"- {f.get('finding_id')}: {f.get('title') or f.get('description')} "
            f"(host: {', '.join(hosts) or 'unknown'}, verdict: {athena.get('highest_verdict', 'unknown')}, "
            f"notified {notif.get('sent_at')} via {', '.join(notif.get('channels') or []) or 'unknown channel'})"
        )
    answer = (
        f"Hermes <Reporter> here -- recently notified threats (last {hours}h):\n" + "\n".join(lines) +
        "\n\nAsk about any one of these (e.g. \"more insight on <finding id>\") for the full agent breakdown."
    )
    return ThreatLookupOutcome(kind="answered", answer=answer)


async def get_threat_insight(question: str) -> ThreatLookupOutcome:
    """Full multi-agent breakdown for one finding -- everything Venus,
    Athena, Orion, Ariadne, and Themis produced, plus the notification
    record itself, not just the summary that was emailed."""
    from services.database_data_service import DatabaseDataService

    svc = DatabaseDataService()
    finding_id = _extract_finding_id(question)
    finding = svc.get_finding(finding_id) if finding_id else None

    if not finding:
        try:
            findings = svc.get_findings(data_source="sentinelone", limit=200)
        except Exception as e:  # noqa: BLE001
            return ThreatLookupOutcome(kind="execution_error", error=str(e))

        words = {w for w in re.findall(r"[a-z0-9\-\.]+", question.lower()) if len(w) > 3 and w not in _STOPWORDS}
        candidates = []
        for f in findings:
            hosts = (f.get("entity_context") or {}).get("hostnames") or []
            haystack = " ".join(str(x) for x in [f.get("title"), f.get("description"), *hosts]).lower()
            if haystack and any(w in haystack for w in words):
                candidates.append(f)

        if len(candidates) == 1:
            finding = candidates[0]
        elif len(candidates) > 1:
            options = "\n".join(f"- {c.get('finding_id')}: {c.get('title')}" for c in candidates[:5])
            return ThreatLookupOutcome(
                kind="needs_clarification",
                clarifying_question=f"Multiple recent threats match -- which one?\n{options}",
            )

    if not finding:
        return ThreatLookupOutcome(
            kind="needs_clarification",
            clarifying_question="Which threat? Give me a finding ID (looks like s1-...), or the affected hostname/process name.",
        )

    enrichment = finding.get("ai_enrichment") or {}
    entity_context = finding.get("entity_context") or {}
    venus = enrichment.get("venus_investigator") or {}
    athena = enrichment.get("athena_threat_intel") or {}
    orion = enrichment.get("orion_threat_hunter") or {}
    ariadne = enrichment.get("ariadne_correlator") or {}
    themis = enrichment.get("themis_compliance_review") or {}
    notif = enrichment.get("notification")

    threat_type = finding.get("title") or finding.get("description") or finding.get("finding_id")
    parts = [
        "Hermes <Reporter> here -- here's what I have on that.",
        "",
        f"THREAT: {threat_type} (finding_id: {finding.get('finding_id')})",
        "",
        f"Endpoint(s): {', '.join(entity_context.get('hostnames') or []) or 'unknown'}",
        "",
        f"Time reported: {finding.get('timestamp')}",
        "",
        f"Detection name: {threat_type}",
        "",
        f"Classification bucket: {entity_context.get('classification') or 'n/a'} (SentinelOne's own coarse "
        f"MANUAL/MALWARE/RANSOMWARE category) | Severity: {finding.get('severity')}",
    ]

    if notif:
        parts += ["", f"Notified: {notif.get('sent_at')} via {', '.join(notif.get('channels') or []) or 'unknown'}"]

    if venus:
        parts += ["", f"Venus (Investigator): {venus.get('assessment') or 'no assessment produced'}"]

    if athena:
        parts += ["", f"Athena (Threat Intel): verdict={athena.get('highest_verdict', 'unknown')}, "
                       f"sources checked={', '.join(athena.get('reputation_sources_used') or []) or 'none configured'}"]
        if athena.get("narrative"):
            parts += ["", athena["narrative"]]
        for p in (athena.get("processes") or [])[:5]:
            rep = p.get("reputation") or {}
            family = rep.get("threat_label") or rep.get("threat_category")
            parts.append(
                f"  - process: {p.get('process_path')} | sha256={p.get('sha256')} | verdict={rep.get('verdict', 'unknown')}"
                + (f" | exact threat family: {family}" if family else "")
            )
        for n in (athena.get("network") or [])[:5]:
            rep = n.get("reputation") or {}
            parts.append(f"  - connection: {n.get('ip')}:{n.get('port')} | verdict={rep.get('verdict', 'unknown')}")

    if orion:
        pending = orion.get("pending_templates") or []
        parts += ["", f"Orion (Threat Hunter): {orion.get('kind', 'not dispatched')}"
                      + (f" -- {len(pending)} template(s) awaiting your confirmation: {', '.join(pending)}" if pending else "")]

    if ariadne:
        parts += ["", f"Ariadne (Correlator): {len(ariadne.get('clusters') or [])} cluster(s) found in its sample"]

    if themis:
        notes = themis.get("notes") or []
        parts += ["", "Themis (Compliance review): " + "; ".join(notes)]

    return ThreatLookupOutcome(kind="answered", answer="\n".join(parts))


async def answer_threat_query(question: str) -> ThreatLookupOutcome:
    if re.search(r"\bnotif", question.lower()) and not _FINDING_ID_RE.search(question):
        return await list_recent_notified_threats()
    return await get_threat_insight(question)


async def answer_as_hermes(question: str) -> ThreatLookupOutcome:
    """Entry point for when the user has explicitly selected Hermes
    <Reporter> as the active agent (explicit user request, 2026-08-05:
    make the notification agent "accessible via the chat interface, so
    users can still come back... and ask it further questions"). Unlike
    answer_threat_query (keyword-gated, used when no specific agent is
    selected), this always tries to help with whatever's asked, and
    falls back to a named referral -- never a bare "I don't know" -- when
    the question is genuinely outside notified-threat lookups."""
    outcome = await answer_threat_query(question)
    if outcome.kind == "answered":
        return outcome

    referral = suggest_referral(question)
    if referral:
        return ThreatLookupOutcome(
            kind="answered",
            answer=(
                f"Hermes <Reporter> here -- that's outside what I track (notified threats and their full agent "
                f"breakdown). That sounds like a job for {referral} -- select them and ask the same question, "
                "and they should be able to help."
            ),
        )

    # No lexical hint either -- keep the original clarifying question
    # rather than guess at a referral with nothing to base it on.
    return outcome
