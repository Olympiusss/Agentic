"""Multi-agent synergy dispatcher (explicit user request, 2026-08-04:
"we want each sub agent actively working 24/7, individually and
together... if subagent investigator drops a finding, hunter subagent
should hunt what was dropped... there should be established synergy
amongst all subagents. They should be reporting to the compliance
agent, which should be checking in on other agents performance asides
them reporting to it").

Architecture (matches the pattern every agentic-SOC product researched
for this build actually uses -- supervisor + shared mutable state, not
agents calling each other peer-to-peer; see SentinelOne Purple AI,
Cortex XSIAM, Torq HyperSOC, and Anthropic's own multi-agent writeup):

- **Blackboard**: `Finding.ai_enrichment` (existing JSONB column,
  services/database_data_service.py's update_finding). Each specialist's
  output is written under its own pantheon-alias key. No agent calls
  another agent directly -- every step reads the finding row, writes its
  own key, and the next step (or Themis) reads the accumulated state.
- **Dispatcher**: Zeus (run_synergy_pipeline, this module's entry point)
  runs the chain in a fixed, auditable order and gates each step behind
  the previous step's confidence/verdict -- not "always run everything."
  Concretely: Athena's artifact/reputation check only escalates to
  Orion's hunt when a malicious/suspicious verdict is found (confidence
  gate, same principle CrowdStrike Charlotte AI and the Panther
  governance writeup both use), and every step's outcome (including
  failures) is recorded, never silently dropped.
- **Oversight**: Themis's review is not passive log storage -- it reads
  what each agent actually produced and flags concrete problems (empty/
  skipped steps, ungrounded claims, contradictions between agents), then
  writes its own verdict into the same blackboard. This is the
  concrete, per-finding form of "checking in on other agents'
  performance," not just receiving their reports.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SWEEP_AGENT_KEYS = ["venus_investigator", "athena_threat_intel", "orion_threat_hunter", "ariadne_correlator"]

# Runtime-hardening gap fixed 2026-08-18 (idempotency audit finding):
# capabilities/notifier.py's notify_telegram/notify_email had zero
# duplicate-send protection -- a retried or re-invoked Phase 1/2 call for
# the same finding would send a second real email/Telegram message with
# nothing to stop it. Reuses daemon/dedup.py's RedisDedupSet directly --
# it's already exactly this primitive (namespace-scoped, Redis-backed
# with TTL + in-memory fallback), proven in production via
# daemon/poller.py's alert dedup. Lazily constructed (not at import time)
# so importing this module never requires REDIS_URL to be resolvable.
_notification_dedup = None


def _get_notification_dedup():
    global _notification_dedup
    if _notification_dedup is None:
        from daemon.dedup import RedisDedupSet

        _notification_dedup = RedisDedupSet("notification")
    return _notification_dedup


def _any_channel_sent(results: list) -> bool:
    """True if at least one NotifyResult actually reports kind == "sent".
    Pure/testable in isolation from the Redis-backed guard itself -- a
    prior attempt that only hit "not_configured"/"execution_error" must
    NOT be treated as "already sent", so a genuine retry (e.g. after
    fixing SMTP config) can still go through rather than being
    permanently blocked by one earlier failed attempt."""
    return any(getattr(r, "kind", None) == "sent" for r in results)


@dataclass
class SynergyStepResult:
    agent: str  # pantheon alias, e.g. "venus_investigator"
    kind: str  # "ran" | "skipped" | "error"
    summary: str
    detail: dict = field(default_factory=dict)


@dataclass
class SynergyOutcome:
    kind: str  # "answered" | "execution_error"
    finding_id: str = ""
    steps: list[SynergyStepResult] = field(default_factory=list)
    highest_verdict: str = "unknown"
    compliance_notes: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _merge_entity_context(finding_id: str, updates: dict) -> None:
    """Merges real, discovered fields (e.g. Athena's external IPs) into
    Finding.entity_context -- distinct from _write_blackboard's
    ai_enrichment writes. entity_context is what services/
    graph_builder_service.py's Entity Graph actually reads, so without
    this the graph would only ever show whatever the poller had at
    ingestion time (just a hostname) and never the network relationships
    Athena's PowerQuery pull actually finds. List-valued keys are unioned
    with whatever's already there, not overwritten. Best-effort, same as
    _write_blackboard -- never raises."""
    try:
        from services.database_data_service import DatabaseDataService

        svc = DatabaseDataService()
        existing = svc.get_finding(finding_id) or {}
        context = dict(existing.get("entity_context") or {})
        for key, value in updates.items():
            if isinstance(value, list):
                merged = list(context.get(key) or [])
                for item in value:
                    if item and item not in merged:
                        merged.append(item)
                context[key] = merged
            else:
                context[key] = value
        svc.update_finding(finding_id, entity_context=context)
    except Exception as e:  # noqa: BLE001
        logger.error("Entity context merge failed for finding %s: %s", finding_id, e)


def _write_blackboard(finding_id: str, key: str, value: dict) -> None:
    """Best-effort append into Finding.ai_enrichment[key]. Never raises --
    a persistence failure shouldn't take down the analysis chain that
    already ran; it's logged and the caller still gets the in-memory
    SynergyOutcome either way."""
    try:
        from services.database_data_service import DatabaseDataService

        svc = DatabaseDataService()
        existing = svc.get_finding(finding_id) or {}
        enrichment = dict(existing.get("ai_enrichment") or {})
        enrichment[key] = value
        svc.update_finding(finding_id, ai_enrichment=enrichment)
    except Exception as e:  # noqa: BLE001
        logger.error("Blackboard write failed for finding %s key %s: %s", finding_id, key, e)


async def _run_venus_step(finding_id: str, alert_id: Optional[str]) -> SynergyStepResult:
    """Venus (Investigator): reconstruct the attack-chain timeline. Split
    out to a standalone coroutine (2026-08-05) so it can run concurrently
    with Athena below -- the two are independent (different inputs,
    different SentinelOne calls), and running them sequentially was pure,
    avoidable latency against the 3-minute notify-with-full-report SLA."""
    if not alert_id:
        return SynergyStepResult(agent="venus_investigator", kind="skipped", summary="no alert_id available")

    from capabilities.investigator import run_investigator

    try:
        inv = await run_investigator(alert_id)
        step = SynergyStepResult(
            agent="venus_investigator", kind="ran" if inv.kind == "answered" else "error",
            summary=f"timeline: {len(inv.timeline)} events across {len(inv.affected_hosts)} host(s)"
            if inv.kind == "answered" else (inv.error or inv.kind),
            detail={"timeline_len": len(inv.timeline), "affected_hosts": inv.affected_hosts, "assessment": inv.assessment},
        )
        _write_blackboard(finding_id, "venus_investigator", asdict(inv))
        return step
    except Exception as e:  # noqa: BLE001
        return SynergyStepResult(agent="venus_investigator", kind="error", summary=str(e))


async def _run_athena_step(finding_id: str, storyline_id: Optional[str]) -> tuple[SynergyStepResult, str]:
    """Athena (Threat Intel): artifact + reputation + signed-verification
    analysis. Returns (step, highest_verdict) since Orion's gate below
    needs the verdict Athena computed."""
    if not storyline_id:
        return SynergyStepResult(agent="athena_threat_intel", kind="skipped", summary="no storyline_id available"), "unknown"

    from capabilities.artifact_analysis import analyze_storyline_artifacts

    try:
        art = await analyze_storyline_artifacts(storyline_id)
        highest_verdict = art.highest_verdict if art.kind == "answered" else "unknown"
        if art.kind == "answered":
            step = SynergyStepResult(
                agent="athena_threat_intel", kind="ran",
                summary=(
                    f"{len(art.processes)} process artifact(s), {len(art.network_connections)} external "
                    f"connection(s) -- verdict={art.highest_verdict} "
                    f"(sources: {', '.join(art.reputation_sources_used) or 'none configured'})"
                ),
                detail={
                    "processes": [
                        {"path": p.process_path, "sha256": p.sha256, "reputation": p.reputation} for p in art.processes
                    ],
                    "network": [
                        {"ip": n.dst_ip, "port": n.dst_port, "reputation": n.reputation} for n in art.network_connections
                    ],
                    "highest_verdict": art.highest_verdict,
                },
            )
        else:
            step = SynergyStepResult(agent="athena_threat_intel", kind="error", summary=art.error or "unknown error")
        _write_blackboard(finding_id, "athena_threat_intel", asdict(art))
        dest_ips = [n.dst_ip for n in art.network_connections if n.dst_ip]
        if dest_ips:
            _merge_entity_context(finding_id, {"dest_ips": dest_ips})
        return step, highest_verdict
    except Exception as e:  # noqa: BLE001
        return SynergyStepResult(agent="athena_threat_intel", kind="error", summary=str(e)), "unknown"


async def run_synergy_pipeline(
    finding_id: str, storyline_id: Optional[str], alert_id: Optional[str], detected_at: Optional[str] = None,
) -> SynergyOutcome:
    """Zeus's dispatch chain for one SentinelOne-sourced finding.
    storyline_id/alert_id may be None (e.g. an alert with no storyline) --
    each step degrades gracefully rather than failing the whole chain.

    Two-phase notification (explicit user request, 2026-08-05: notify
    immediately with raw alert details, THEN investigate, with the full
    investigative report out within at most 3 minutes of the alert
    firing). Phase 1 (raw alert, near-instant) fires from
    daemon/poller.py at ingestion, before this function is even called.
    This function is Phase 2: Venus and Athena run CONCURRENTLY (they're
    independent), and the investigative-report notification fires the
    moment they're both done -- not after Orion/Ariadne/Themis, which
    continue afterward for the blackboard/system-health record but were
    never part of what the user asked the report to contain (reputation,
    Deep Visibility, process/hash/signing detail -- all Venus+Athena's
    job). `detected_at` (the alert's own detectedAt, not "now") is the
    SLA clock's start; passed through so the phase-2 notifier can log
    real elapsed time against the 3-minute budget instead of guessing."""
    steps: list[SynergyStepResult] = []
    verdict_rank = {"malicious": 3, "suspicious": 2, "clean": 1, "unknown": 0}

    venus_step, (athena_step, highest_verdict) = await asyncio.gather(
        _run_venus_step(finding_id, alert_id),
        _run_athena_step(finding_id, storyline_id),
    )
    steps.append(venus_step)
    steps.append(athena_step)

    # Phase 2 fires here -- the investigative report is complete the
    # moment the two agents that actually produce its content are done.
    await _notify_investigative_report(finding_id, highest_verdict, detected_at)

    # -- Orion (Threat Hunter): confidence-gated -- only dispatched when
    # Athena's reputation check actually found something malicious/
    # suspicious. This is the concrete "investigator drops a finding,
    # hunter hunts what was dropped" chaining, gated the same way every
    # researched product gates autonomous cross-agent action (confidence
    # threshold), not "hunt on every single alert regardless of signal." --
    if verdict_rank.get(highest_verdict, 0) >= verdict_rank["suspicious"]:
        from capabilities.threat_hunter import run_threat_hunter

        try:
            hunt = await run_threat_hunter(window_hours=24, confirmed=False)
            steps.append(SynergyStepResult(
                agent="orion_threat_hunter",
                kind="ran" if hunt.kind in ("answered", "needs_confirmation") else "error",
                summary=(
                    f"hunt gated by Athena's '{highest_verdict}' verdict -- "
                    + (f"{len(hunt.pending_templates)} template(s) await human confirmation"
                       if hunt.kind == "needs_confirmation" else f"{len(hunt.hits)} template(s) run")
                ),
                detail={"kind": hunt.kind, "pending_templates": hunt.pending_templates},
            ))
            _write_blackboard(finding_id, "orion_threat_hunter", asdict(hunt))
        except Exception as e:  # noqa: BLE001
            steps.append(SynergyStepResult(agent="orion_threat_hunter", kind="error", summary=str(e)))
    else:
        steps.append(SynergyStepResult(
            agent="orion_threat_hunter", kind="skipped",
            summary=f"not dispatched -- Athena's verdict ('{highest_verdict}') did not clear the suspicious/malicious gate",
        ))

    # -- Ariadne (Correlator): is this part of a broader pattern? --
    from capabilities.correlator import run_correlator

    try:
        corr = await run_correlator(sample_size=20)
        steps.append(SynergyStepResult(
            agent="ariadne_correlator", kind="ran" if corr.kind == "answered" else "error",
            summary=f"{len(corr.clusters)} cluster(s) found in a {corr.sample_size}-alert sample" if corr.kind == "answered" else (corr.error or "error"),
            detail={"cluster_count": len(corr.clusters)},
        ))
        _write_blackboard(finding_id, "ariadne_correlator", asdict(corr))
    except Exception as e:  # noqa: BLE001
        steps.append(SynergyStepResult(agent="ariadne_correlator", kind="error", summary=str(e)))

    # -- Themis (Compliance & Debug): active review, not passive storage --
    compliance_notes: list[str] = []
    for step in steps:
        if step.kind == "error":
            compliance_notes.append(f"{step.agent} errored: {step.summary}")
        elif step.agent == "venus_investigator" and step.kind == "ran" and step.detail.get("timeline_len", 0) == 0:
            compliance_notes.append("venus_investigator ran but returned an empty timeline -- verify storyline data is real, not silently defaulted")
        elif step.agent == "athena_threat_intel" and step.kind == "ran" and not step.detail.get("processes") and not step.detail.get("network"):
            compliance_notes.append("athena_threat_intel found no artifacts at all -- confirm this storyline genuinely has no process/network events, not a query failure being swallowed")
    if highest_verdict in ("malicious", "suspicious") and not any(s.agent == "orion_threat_hunter" and s.kind == "ran" for s in steps):
        compliance_notes.append(f"verdict was '{highest_verdict}' but Orion was not dispatched -- check the confidence-gate logic")
    if not compliance_notes:
        compliance_notes.append("no anomalies found in this cycle's agent outputs")

    _write_blackboard(finding_id, "themis_compliance_review", {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "notes": compliance_notes,
        "steps_reviewed": [s.agent for s in steps],
    })

    # Decision capture (unified-schema foundation, Phase 2, 2026-08-20):
    # this pipeline never wrote an AIDecisionLog row before -- only
    # daemon/orchestrator.py's investigation orchestrator did, so the
    # actual per-finding "agent draft" this pipeline produces was
    # invisible to the approve/modify/override/escalate decision-capture
    # flow. agent_id is "zeus_pipeline" (a new identity, distinct from
    # both services/soc_agents.py's AGENT_CONFIGS keys and this file's own
    # pantheon blackboard aliases): the verdict here spans multiple agents
    # (Venus + Athena + gated Orion), not any single one of them. Goes
    # through database/service.py::create_ai_decision() -- the same real
    # service-layer method the API and orchestrator already use -- rather
    # than a raw ORM write, for consistency with how this file already
    # goes through DatabaseDataService for the blackboard. Best-effort,
    # never raises -- same pattern as every other persistence call here.
    try:
        import uuid

        from database.service import DatabaseService

        confidence_by_verdict = {"malicious": 0.95, "suspicious": 0.7, "clean": 0.4, "unknown": 0.1}
        reasoning = "; ".join(s.summary for s in steps if s.kind == "ran" and s.summary) or "no agent produced a usable summary"
        DatabaseService().create_ai_decision(
            decision_id=f"zeus-{uuid.uuid4().hex[:20]}",
            agent_id="zeus_pipeline",
            decision_type="triage_verdict",
            confidence_score=confidence_by_verdict.get(highest_verdict, 0.1),
            reasoning=reasoning,
            recommended_action=f"verdict={highest_verdict}",
            finding_id=finding_id,
            decision_metadata={
                "steps": [asdict(s) for s in steps],
                "compliance_notes": compliance_notes,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.error("AI decision log write failed for finding %s: %s", finding_id, e)

    return SynergyOutcome(
        kind="answered", finding_id=finding_id, steps=steps,
        highest_verdict=highest_verdict, compliance_notes=compliance_notes,
    )


def _notification_emails() -> Optional[list[str]]:
    """The single point of control for alert-notification email recipients
    -- both notify_new_alert_immediate (Phase 1) and
    _notify_investigative_report (Phase 2) call this, so gating it here
    (rather than duplicating a check in each) turns email off/on for both
    at once. Added 2026-08-20 (explicit user request: a real toggle that
    doesn't require clearing/re-adding real SMTP credentials in docker/.env
    every time). Deliberately scoped to email only -- returning None here
    makes capabilities/notifier.py::notify_new_threat() skip the email
    channel, but Telegram (a separate channel/toggle) is unaffected.
    Default true (matches every existing DAEMON_* boolean toggle's
    fail-open convention in this codebase) so this is a no-op for anyone
    who hasn't set the var. Resolves DB (Settings UI -> system_config) before
    the env var, via services/runtime_config.py, so flipping the switch
    takes effect live without a container restart."""
    import os

    from services.runtime_config import get_notification_setting

    if not get_notification_setting("email_notifications_enabled", True):
        return None

    emails_raw = os.getenv("THREAT_NOTIFICATION_EMAILS", "")
    return [e.strip() for e in emails_raw.split(",") if e.strip()] or None


async def notify_new_alert_immediate(finding_id: str, alert: dict) -> None:
    """Phase 1 of the two-phase notification (explicit user request,
    2026-08-05: "for every new threat or new alert that comes in, the
    user should be notified immediately with the threat details or alert
    details"; refined 2026-08-18: "stating the respective client name and
    then the alert notification -- just a simple notif"). Fired from
    daemon/poller.py at ingestion, straight off the raw SentinelOne alert
    dict -- deliberately no Deep Visibility, no reputation lookups,
    nothing that takes real wall-clock time, so this reaches the user in
    well under a second. Client name comes from an in-memory dict lookup
    (services.sentinelone_dashboard_service.get_site_for_endpoint,
    populated by that service's existing 5-minute inventory refresh) so
    it doesn't add any I/O of its own. The full investigative report
    (Phase 2, _notify_investigative_report below) follows once Venus and
    Athena finish, targeted at at most 3 minutes after
    `alert['detectedAt']`."""
    try:
        from capabilities.notifier import notify_new_threat
        from services.sentinelone_dashboard_service import get_site_for_endpoint

        dedup = _get_notification_dedup()
        dedup_key = f"{finding_id}:phase1"
        if await dedup.is_processed(dedup_key):
            logger.info(f"Immediate alert notification for {finding_id} already sent -- skipping duplicate dispatch")
            return

        asset = alert.get("asset") or {}
        detection_source = alert.get("detectionSource") or {}
        name = alert.get("name") or "SentinelOne Alert"
        client_name = get_site_for_endpoint(asset.get("name") or "") or "unknown client"

        summary = (
            "\U0001F6A8 NEW ALERT \U0001F6A8\n\n"
            f"Client: {client_name}\n\n"
            "Hermes <Reporter> here -- new alert just came in from SentinelOne. "
            "Full investigative analysis (Deep Visibility, threat-intel reputation, signed-binary verification) "
            "is starting now and will follow as a separate report within a few minutes.\n\n"
            f"[{(alert.get('severity') or 'unknown').upper()}] {name}\n\n"
            f"Endpoint: {asset.get('name') or 'unknown'}\n\n"
            f"Detected at: {alert.get('detectedAt') or 'unknown'}\n\n"
            f"Detection source: {detection_source.get('product') or 'unknown'} ({detection_source.get('vendor') or 'SentinelOne'})\n\n"
            f"Classification: {alert.get('classification') or 'n/a'} | Analyst verdict: {alert.get('analystVerdict') or 'UNDEFINED'}\n\n"
            "Best Regards,\n"
            "Hermes <Reporter>"
        )

        results = await notify_new_threat(
            summary,
            to_email_addresses=_notification_emails(),
            subject=f"\U0001F6A8 NEW ALERT -- Hermes <Reporter>: {name} on {client_name}",
            telegram_lead="\U0001F6A8 NEW ALERT -- Hermes <Reporter> (full report follows shortly):",
        )
        sent_channels = [r.channel for r in results if r.kind == "sent"]
        for r in results:
            if r.kind == "sent":
                logger.info(f"Immediate alert notification sent via {r.channel} for {finding_id}")
            elif r.kind == "execution_error":
                logger.warning(f"Immediate alert notification via {r.channel} failed: {r.error}")

        if _any_channel_sent(results):
            await dedup.mark_processed(dedup_key)

        _write_blackboard(finding_id, "notification_immediate", {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "channels": sent_channels,
            "content": summary,
            "client_name": client_name,
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"Immediate alert notification dispatch failed for {finding_id}: {e}")


_HASH_REPUTATION_LABELS = {"clean": "Known", "suspicious": "Unknown", "malicious": "Malicious"}


def _map_hash_reputation(verdict: Optional[str]) -> str:
    """Maps a HashReputation.verdict ("malicious"/"suspicious"/"clean"/
    "unknown"/"not_configured"/"not_found"/"execution_error") to the
    exact three-value enum the user's report template uses (Known/
    Unknown/Malicious -- see the template's Field Notes table: "if
    Malicious, this template does not apply; use containment escalation
    format instead"). Pure function, unit-testable without live calls.
    Anything that isn't a clear clean/suspicious/malicious verdict
    (unconfigured providers, lookup errors, no data) maps to "Unknown" --
    never silently upgraded to "Known", since that would understate risk
    on a genuinely un-checked artifact."""
    return _HASH_REPUTATION_LABELS.get(verdict or "", "Unknown")


_MAX_ACTIVITY_LABEL_LEN = 100


def _short_activity_label(title: Optional[str], description: Optional[str], hostname: str) -> str:
    """A short, subject-line/greeting-safe activity descriptor. Bug found
    via a real end-to-end run against a live finding (2026-08-18): when
    `finding.title` is null (common -- many SentinelOne-sourced findings
    have no title, only a long multi-sentence `description`), the naive
    `title or description` fallback embedded the FULL raw description
    directly into the subject line and the "We have observed {X} on
    endpoint..." greeting sentence, producing an unreadable wall of text
    instead of a short activity name. Falls back to the description's
    first sentence (capped, never truncated mid-word) when there's no
    title; the full raw description is still passed to the narrative
    synthesis call separately for grounding, this is only the short label
    used in the subject/greeting. Pure function, unit-testable."""
    if title and title.strip():
        return title.strip()
    if description and description.strip():
        first_sentence = description.strip().split(". ", 1)[0].split(".\n", 1)[0].strip()
        if len(first_sentence) > _MAX_ACTIVITY_LABEL_LEN:
            truncated = first_sentence[:_MAX_ACTIVITY_LABEL_LEN].rsplit(" ", 1)[0]
            return f"{truncated}..."
        return first_sentence
    return f"Detection on {hostname}"


def _map_digital_signature(signed_status: Optional[str]) -> str:
    """Maps SentinelOne's raw src.process.signedStatus string to the
    template's SIGNED_VALID / SIGNED_INVALID / UNSIGNED enum. The exact
    raw values SentinelOne returns were never live-confirmed this session
    (only that the field itself populates, e.g. "signed" -- see
    capabilities/artifact_analysis.py's module docstring) -- pattern-
    matched here rather than an exact-value lookup table so a raw value
    like "signed" or "Signed and Verified" still resolves correctly, but
    anything genuinely unrecognized is returned as-is (not force-fit into
    one of the three enum values) so the report never claims a signature
    state the evidence doesn't support."""
    if not signed_status:
        return "not available"
    s = signed_status.strip().lower()
    if "invalid" in s or "expired" in s or "revoked" in s or "untrusted" in s:
        return "SIGNED_INVALID"
    if "unsigned" in s or "not signed" in s or s == "none":
        return "UNSIGNED"
    if "valid" in s or "signed" in s or "trusted" in s or "verified" in s:
        return "SIGNED_VALID"
    return signed_status


# The user's own exact sample (explicit user request, 2026-08-18: "This is
# the exact template, tone, and style of our analysis report") -- embedded
# verbatim as an in-context style reference for the narrative synthesis
# call below. The deterministic shell in _notify_investigative_report
# reproduces this structure directly (subject line, greeting, Event
# Details bullets, Note, Recommendations, sign-off); only the three prose
# sections (verification finding, Note paragraph, Recommendations bullets)
# are LLM-synthesized, everything else is grounded field interpolation.
_SAMPLE_REPORT = """Subject: Security Alert Notification \u2014 Remote Access Tool Execution on WKS-FIN-0231

Hello Team,

We have observed the execution of the AnyDesk remote access application (AnyDesk.exe) on endpoint WKS-FIN-0231, associated with the user CORPDOM\\a.bello.

Further investigation indicates that the executable is a legitimate, digitally signed AnyDesk application installed under the standard Program Files directory. However, as AnyDesk is a remote access tool capable of establishing inbound and outbound remote desktop sessions and file transfers, we would like to confirm whether its use is authorized within your environment and whether the user is permitted to use this application.

Event Details:
* Hostname: WKS-FIN-0231
* Process User: CORPDOM\\a.bello
* Process Name: AnyDesk.exe
* File Path: C:\\Program Files (x86)\\AnyDesk\\AnyDesk.exe
* Originating Process: explorer.exe
* Digital Signature: SIGNED_VALID
* Hash Reputation: Known
* Timestamp: Aug 17, 2026, 03:42 PM
* Event URL: [Investigation Details](https://example-console.invalid/investigations/00000000-0000-0000-0000-000000000000)

Note:
AnyDesk is a legitimate remote access tool commonly used for remote support and administration. While it is widely used by IT support personnel, it is also frequently abused by threat actors for unauthorized remote access, persistence, and data transfer, as it does not always require administrative installation. Therefore, it is important to verify that its installation and usage are approved in accordance with the organization's security policies and that the user is authorized to use the application.

Recommendations:
* Verify whether AnyDesk is an approved application in your environment.
* Confirm whether CORPDOM\\a.bello is authorized to use AnyDesk as part of their job responsibilities.
* If its usage is not authorized, uninstall the software and review recent session logs for unexpected remote connections.

Best Regards,"""


_REPORT_NARRATIVE_INSTRUCTIONS = """You are Hermes <Reporter>, writing a SOC investigative-analysis email to the analyst team. Match the EXACT tone, register, and structure of this real, user-approved example -- it is a style reference, not content to reuse:

---
{sample}
---

Ground every claim in the retrieved evidence below -- never invent a hostname, hash, username, process, publisher, verdict, or fact not present in it. If something genuinely isn't available (e.g. no process-user data on a Linux endpoint, reputation providers unconfigured, or no network artifacts on this storyline), say so plainly rather than guessing or padding.
{tone_instruction}

Write exactly three sections, each starting on its own line with the marker shown below, and nothing else outside them:

VERIFICATION:
1-3 sentences on what the observed process/application actually is, based strictly on the retrieved evidence (signing status, publisher, reputation, any known legitimate use the evidence itself supports), and whether it needs confirming with the client -- mirror the sample's "Further investigation indicates that..." opening and register.

NOTE:
One short paragraph on the dual-use / risk context of this specific application or activity -- why it matters even where reputation came back clean, matching the sample's "Note:" paragraph tone (measured and factual, not alarmist, unless the evidence genuinely shows malicious activity).

RECOMMENDATIONS:
2-4 lines, each starting with "* ", concrete and specific to this alert's actual evidence (not generic boilerplate) -- what the analyst/client should verify or do next.

Retrieved evidence:
{evidence_block}
"""


async def _synthesize_report_narrative(
    client_name: str, hostname: str, process_line: str, process_user: Optional[str],
    parent_process: Optional[str], signing_line: str, hash_reputation_label: str,
    network_block: str, athena_narrative: Optional[str], siem_cross_check: Optional[str],
    highest_verdict: str, detection_description: Optional[str] = None,
) -> tuple[str, str, list[str]]:
    """Returns (verification, note, recommendation_lines) -- always
    returns something usable, even on total synthesis failure (generic,
    clearly-labeled fallback text rather than leaving the email broken).
    A malicious verdict shifts the prompt's tone toward urgency/
    containment (explicit user answer to the escalation-template
    clarifying question, 2026-08-18: "we would integrate for client
    receival later, for now it is the analysts" -- interpreted as: same
    template, urgency folded into tone for now, not a second hardcoded
    template; flagged for correction if that reading is wrong)."""
    from capabilities.synthesis import synthesize, split_sections

    tone_instruction = (
        "This alert's reputation verdict is MALICIOUS -- shift tone toward urgency and containment: the "
        "VERIFICATION section should state plainly that this is an active threat requiring immediate action, "
        "not a routine authorization check, and RECOMMENDATIONS should lead with containment steps (isolate the "
        "endpoint, block the indicator) before the AnyDesk-style 'confirm authorization' framing."
        if highest_verdict == "malicious" else
        "This alert's reputation verdict is not currently malicious -- keep the measured, 'please confirm this is "
        "authorized' register the sample uses, do not manufacture urgency the evidence doesn't support."
    )

    evidence_lines = [
        f"Client: {client_name}",
        f"Hostname: {hostname}",
        f"Detection description (SentinelOne's own, full text -- ground the VERIFICATION/NOTE sections in this, "
        f"not just the short subject-line label): {detection_description or 'not available'}",
        f"Process: {process_line}",
        f"Process user: {process_user or 'not available'}",
        f"Originating process: {parent_process or 'not available'}",
        f"Code-signing: {signing_line}",
        f"Hash reputation: {hash_reputation_label}",
        f"Network artifacts: {network_block}",
    ]
    if siem_cross_check:
        evidence_lines.append(f"AlienVault (SIEM) cross-check for this client: {siem_cross_check}")
    if athena_narrative:
        evidence_lines.append(f"Athena's own investigative write-up: {athena_narrative[:1200]}")

    prompt = _REPORT_NARRATIVE_INSTRUCTIONS.format(
        sample=_SAMPLE_REPORT, tone_instruction=tone_instruction, evidence_block="\n".join(evidence_lines),
    )

    text, err = await synthesize(prompt, agent_id="reporter")
    if err or not text:
        logger.warning("Investigative report narrative synthesis failed: %s", err)
        return _FALLBACK_VERIFICATION, _FALLBACK_NOTE, [_FALLBACK_RECOMMENDATION]

    return _parse_narrative_sections(text)


_FALLBACK_VERIFICATION = (
    "Automated narrative synthesis was unavailable for this alert -- the deterministic fields above "
    "(hostname, process, signing, and reputation) are directly grounded in retrieved evidence; a human "
    "analyst should review them and confirm authorization/legitimacy manually."
)
_FALLBACK_NOTE = (
    "No further contextual analysis is available for this alert -- treat the fields above as the "
    "complete grounded evidence set and evaluate risk manually."
)
_FALLBACK_RECOMMENDATION = "Review the Event Details above and confirm authorization directly with the client."


def _parse_narrative_sections(text: str) -> tuple[str, str, list[str]]:
    """Splits a raw synthesize() response into (verification, note,
    recommendation_lines). Pure function, unit-testable without mocking
    the LLM call.

    Bug found via a real end-to-end run 2026-08-18: the model sometimes
    bolds its own section markers ("**NOTE:**" instead of "NOTE:") and,
    despite the prompt's "nothing else outside them" instruction,
    occasionally appends a sign-off or a duplicate bold-markdown "Event
    Details" recap after RECOMMENDATIONS. Two defenses against that,
    applied regardless of whether the model actually misbehaves (never
    trust it to comply):
    1. Splitting on the bare marker string leaves a stray "**" (the
       bolded marker's own asterisks) at the PREVIOUS section's tail --
       .strip() alone only trims whitespace, not asterisks, so that
       leftover "**" was leaking into the email verbatim. rstrip("*")
       after strip() clears it without disturbing real content (which is
       prose, not asterisk-terminated).
    2. The recommendations filter matches "* " (asterisk + space)
       specifically, not just a leading "*" -- the bogus trailing content
       observed in that same run used bold-markdown lines like
       "**Hermes**" and "**Hostname:** ..." which start with "*" but not
       "* ", so this filter alone excludes them without needing to
       detect/truncate the bogus section separately."""
    from capabilities.synthesis import split_sections

    verification = split_sections(text, "VERIFICATION:")
    if "NOTE:" in verification:
        verification = verification.split("NOTE:", 1)[0].strip().rstrip("*").strip()
    note = split_sections(text, "NOTE:")
    if "RECOMMENDATIONS:" in note:
        note = note.split("RECOMMENDATIONS:", 1)[0].strip().rstrip("*").strip()
    # NOT split_sections() here -- its lstrip("*") (meant to clean up a
    # bolded "**RECOMMENDATIONS:**" marker) also eats the literal "*" off
    # the first real bullet line immediately following the marker, since
    # lstrip operates on the whole string's leading characters, not
    # per-line. A plain split avoids corrupting real bullet content.
    recommendations_block = text.split("RECOMMENDATIONS:", 1)[1] if "RECOMMENDATIONS:" in text else ""
    recommendation_lines = [
        line.strip() for line in recommendations_block.splitlines() if line.strip().startswith("* ")
    ] or [_FALLBACK_RECOMMENDATION]

    return verification, note, recommendation_lines


async def _get_siem_cross_check(client_name: str) -> Optional[str]:
    """Cross-platform correlation (explicit user request, 2026-08-18:
    "Our agents has access to both platforms. The designated agent should
    be able to traverse solutions to gain deeper insights and
    understanding"). Pulls this client's AlienVault Central (SIEM) alarm/
    event volume alongside the SentinelOne (EDR) Deep Visibility evidence
    Athena already gathered -- only when the client registry actually
    matched this client to a SIEM deployment; returns None (silently
    omitted from the report) for EDR-only clients, unconfigured
    deployments, or any lookup failure -- never fabricated, never surfaced
    as an error to the analyst reading the report."""
    try:
        from services.client_registry_service import find_client
        from services.alienvault_central_service import AVDeployment, get_deployment_alarms, get_deployment_event_count

        record = find_client(client_name)
        if not record or not record.has_siem or not record.av_deployment_fqdn:
            return None

        deployment = AVDeployment(id="", name=record.av_deployment_name or client_name, fqdn=record.av_deployment_fqdn)
        alarms, events = await asyncio.gather(
            get_deployment_alarms(deployment, hours_back=24), get_deployment_event_count(deployment, hours_back=24),
        )
        if alarms.kind != "found" or events.kind != "found":
            return None

        priority_str = ", ".join(f"{k}: {v}" for k, v in alarms.by_priority.items()) or "no priority breakdown"
        return f"{alarms.total} alarm(s) / {events.total} event(s) in the trailing 24h (by priority: {priority_str})"
    except Exception as e:  # noqa: BLE001
        logger.error("SIEM cross-check failed for client %s: %s", client_name, e)
        return None


async def _notify_investigative_report(finding_id: str, highest_verdict: str, detected_at: Optional[str]) -> None:
    """Phase 2: the full SOC-analyst-style investigative report, rewritten
    2026-08-18 to reproduce the user's exact template verbatim (explicit
    user request: "This is the exact template, tone, and style of our
    analysis report" -- see _SAMPLE_REPORT above). Deterministic fields
    (hostname, process, hashes, signing, timestamp, client name) come
    straight from already-retrieved data; the three prose sections
    (verification finding, Note, Recommendations) come from one
    synthesize() call in _synthesize_report_narrative. Fires as soon as
    Venus and Athena (the two agents that actually produce this content)
    are done, not after the rest of the pipeline -- see
    run_synergy_pipeline's docstring. Degrades field-by-field to "not
    available" rather than skipping the notification when a field
    genuinely isn't there (no storyline, no artifacts found, reputation
    providers unconfigured, event URL not yet available -- omitted per
    the template's own Field Notes: "never fabricate; omit the line if
    unavailable")."""
    try:
        from capabilities.notifier import notify_new_threat
        from services.database_data_service import DatabaseDataService
        from services.sentinelone_dashboard_service import get_site_for_endpoint

        dedup = _get_notification_dedup()
        dedup_key = f"{finding_id}:phase2"
        if await dedup.is_processed(dedup_key):
            logger.info(f"Investigative report for {finding_id} already sent -- skipping duplicate dispatch")
            return

        svc = DatabaseDataService()
        finding = svc.get_finding(finding_id)
        if not finding:
            logger.warning(f"Investigative report notification skipped for {finding_id}: finding row not found")
            return

        entity_context = finding.get("entity_context") or {}
        enrichment = finding.get("ai_enrichment") or {}
        athena = enrichment.get("athena_threat_intel") or {}
        processes = athena.get("processes") or []
        network = athena.get("network_connections") or []

        # Prefer the artifact with the worst reputation verdict (the one
        # an analyst would actually want to see first), fall back to the
        # first artifact found, fall back to "not available".
        verdict_rank = {"malicious": 3, "suspicious": 2, "clean": 1}
        top_process = None
        if processes:
            top_process = max(
                processes, key=lambda p: verdict_rank.get((p.get("reputation") or {}).get("verdict"), 0)
            )

        hosts = entity_context.get("hostnames") or []
        hostname = hosts[0] if hosts else "unknown"
        client_name = get_site_for_endpoint(hostname) or "unknown client"

        process_name = "not available"
        process_user = None
        file_path = "not available"
        parent_process = None
        signing_line = "not available"
        hash_reputation_label = "Unknown"
        process_line = "not available (no storyline data, or artifact analysis hasn't completed)"
        if top_process:
            rep = top_process.get("reputation") or {}
            file_path = top_process.get("process_path") or "not available"
            process_name = (file_path.replace("/", "\\").rsplit("\\", 1)[-1]) if file_path != "not available" else "not available"
            process_user = top_process.get("process_user")
            parent_process = top_process.get("parent_process_path")
            signing_line = (
                f"{top_process.get('signed_status') or 'unknown'} -- publisher: {top_process.get('publisher') or 'n/a'}, "
                f"SentinelOne verification: {top_process.get('verified_status') or 'unknown'}"
            )
            hash_reputation_label = _map_hash_reputation(rep.get("verdict"))
            process_line = (
                f"{file_path} | SHA256: {top_process.get('sha256') or 'n/a'} | "
                f"VirusTotal verdict: {rep.get('verdict', 'unknown')} ({rep.get('malicious', 0)} malicious / "
                f"{rep.get('suspicious', 0)} suspicious detections)"
            )

        digital_signature_label = _map_digital_signature(top_process.get("signed_status") if top_process else None)

        network_block = "; ".join(
            f"{n.get('dst_ip')}:{n.get('dst_port') or '?'} (reputation: {(n.get('reputation') or {}).get('verdict', 'unknown')})"
            for n in network
        ) or "no external network artifacts observed on this storyline"

        raw_description = finding.get("description") or ""
        # entity_context.alert_name (daemon/poller.py) is SentinelOne's own
        # short, clean alert label -- preferred over finding.title, which
        # is never actually persisted (Finding has no title column; see
        # the comment where alert_name is set). Falls back to title anyway
        # in case a non-SentinelOne source populates it someday.
        alert_name = entity_context.get("alert_name") or finding.get("title")
        threat_type = _short_activity_label(alert_name, raw_description, hostname)
        timestamp = finding.get("timestamp") or "not available"

        # Event URL: never fabricated (explicit template rule: "never
        # fabricate; omit the line if unavailable") -- the real SentinelOne
        # console deep-link pattern was not supplied this session (user
        # committed to providing it, hasn't yet), so this stays None and
        # the bullet is simply omitted below rather than guessing a URL.
        event_url: Optional[str] = None

        # Cross-platform correlation and the narrative synthesis call are
        # independent of each other's inputs except that the narrative
        # wants the SIEM result as evidence -- fetch SIEM first (fast, a
        # couple of HTTP calls), then synthesize.
        siem_cross_check = await _get_siem_cross_check(client_name) if client_name != "unknown client" else None

        verification, note, recommendation_lines = await _synthesize_report_narrative(
            client_name=client_name, hostname=hostname, process_line=process_line, process_user=process_user,
            parent_process=parent_process, signing_line=signing_line, hash_reputation_label=hash_reputation_label,
            network_block=network_block, athena_narrative=athena.get("narrative"),
            siem_cross_check=siem_cross_check, highest_verdict=highest_verdict,
            detection_description=raw_description or None,
        )

        # SLA instrumentation (explicit user request, 2026-08-05: full
        # report out within at most 3 minutes of the alert firing) --
        # logged for engineering visibility, never silently hidden, but
        # kept out of the client-facing email body (a security report
        # reading "sorry, this took 4 minutes" undermines it more than a
        # clean miss logged internally and fixed).
        elapsed_s = None
        if detected_at:
            try:
                det_dt = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
                if det_dt.tzinfo is None:
                    det_dt = det_dt.replace(tzinfo=timezone.utc)
                elapsed_s = (datetime.now(timezone.utc) - det_dt).total_seconds()
            except ValueError:
                pass
        if elapsed_s is not None:
            if elapsed_s > 180:
                logger.warning(f"Investigative report for {finding_id} took {elapsed_s:.0f}s -- exceeded the 3-minute SLA")
            else:
                logger.info(f"Investigative report for {finding_id} sent {elapsed_s:.0f}s after detection (within 3-minute SLA)")

        user_clause = f", associated with the user {process_user}" if process_user else ""
        event_details = [
            f"* Client: {client_name}",
            f"* Hostname: {hostname}",
            f"* Process User: {process_user or 'not available'}",
            f"* Process Name: {process_name}",
            f"* File Path: {file_path}",
            f"* Originating Process: {parent_process or 'not available'}",
            f"* Digital Signature: {digital_signature_label}",
            f"* Hash Reputation: {hash_reputation_label}",
            f"* Timestamp: {timestamp}",
        ]
        if siem_cross_check:
            event_details.append(f"* AlienVault (SIEM) Cross-Check: {siem_cross_check}")
        if event_url:
            event_details.append(f"* Event URL: [Investigation Details]({event_url})")

        # Subject revised per explicit user request 2026-08-18 ("informed,
        # brief and executive") -- leads with severity and client (the two
        # things an analyst/exec scanning an inbox needs first), drops the
        # generic "Security Alert Notification --" boilerplate, and keeps
        # the red-alert marker consistent with Phase 1's subject for a
        # genuinely malicious verdict.
        severity_label = (finding.get("severity") or "unknown").upper()
        urgency_marker = "\U0001F6A8 URGENT -- " if highest_verdict == "malicious" else ""
        subject = f"{urgency_marker}[{severity_label}] {client_name} -- {threat_type} ({hostname})"

        summary = (
            "Hello Team,\n\n"
            f"We have observed {threat_type} ({process_name}) on endpoint {hostname}{user_clause}.\n\n"
            f"{verification}\n\n"
            "Event Details:\n" + "\n".join(event_details) + "\n\n"
            f"Note:\n{note}\n\n"
            "Recommendations:\n" + "\n".join(recommendation_lines) + "\n\n"
            "Best Regards,\n"
            "Hermes <Reporter>\n\n"
            f"Have questions? Come back to Sentry Agentic and ask me (Hermes) things like \"more insight on {finding_id}\" or "
            "\"what threats have you notified me about.\" If your question needs a different specialist (deeper hunting, "
            "a fresh investigation, CVE lookups), I'll point you to the right agent by name."
        )

        results = await notify_new_threat(
            summary,
            to_email_addresses=_notification_emails(),
            subject=subject,
            telegram_lead="Hermes <Reporter> -- investigative report ready:",
        )
        sent_channels = [r.channel for r in results if r.kind == "sent"]
        for r in results:
            if r.kind == "sent":
                logger.info(f"Investigative report notification sent via {r.channel} for {finding_id}")
            elif r.kind == "execution_error":
                logger.warning(f"Investigative report notification via {r.channel} failed: {r.error}")

        if _any_channel_sent(results):
            await dedup.mark_processed(dedup_key)

        # Persist the notification itself as a blackboard entry -- explicit
        # user request, 2026-08-05: "every external action must be able to
        # be retrieve[d] via the interface." Without this, the only record
        # of what was sent lived in the recipient's inbox; now
        # capabilities/threat_lookup.py can answer "what were you notified
        # about" and "what did that notification say" from chat.
        _write_blackboard(finding_id, "notification", {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "channels": sent_channels,
            "content": summary,
            "client_name": client_name,
            "seconds_after_detection": round(elapsed_s) if elapsed_s is not None else None,
        })
    except Exception as e:  # noqa: BLE001
        logger.error(f"Investigative report notification dispatch failed for {finding_id}: {e}")


@dataclass
class ThemisSweepResult:
    kind: str  # "answered" | "execution_error"
    swept_at: str = ""
    findings_reviewed: int = 0
    findings_never_analyzed: int = 0
    agent_run_counts: dict[str, int] = field(default_factory=dict)
    agent_error_counts: dict[str, int] = field(default_factory=dict)
    reputation_providers_configured: list[str] = field(default_factory=list)
    systemic_issues: list[str] = field(default_factory=list)
    error: Optional[str] = None


async def run_themis_sweep(window_hours: int = 24, stale_after_minutes: int = 10) -> ThemisSweepResult:
    """Themis's standing, periodic system-health sweep -- runs independent
    of any single finding (wired into daemon/scheduler.py's TaskScheduler,
    same pattern as the existing health_check/cleanup tasks), per the
    explicit user request that the compliance agent should be "checking
    in on other agents' performance" continuously, not only when a new
    finding happens to trigger the per-finding review already built into
    run_synergy_pipeline above.

    Looks across every SentinelOne-sourced finding from the last
    `window_hours` and asks systemic questions a single per-finding
    review can't: is one agent's step erroring far more than the others,
    are findings sitting un-analyzed longer than the dispatch retry
    window should ever allow (a real stuck-pipeline signal, not noise),
    and are the reputation providers still configured. Writes its
    verdict to the same system_config store the daemon already uses for
    orchestrator/kafka settings (database/config_service.py) so the
    dashboard and any future conversation can read the last sweep
    without re-running it."""
    import os

    from services.database_data_service import DatabaseDataService

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    stale_cutoff = now - timedelta(minutes=stale_after_minutes)

    try:
        svc = DatabaseDataService()
        findings = svc.get_findings(data_source="sentinelone", limit=500)
    except Exception as e:  # noqa: BLE001
        logger.error("Themis sweep: failed to load findings: %s", e)
        return ThemisSweepResult(kind="execution_error", swept_at=now.isoformat(), error=str(e))

    agent_run_counts = {k: 0 for k in _SWEEP_AGENT_KEYS}
    agent_error_counts = {k: 0 for k in _SWEEP_AGENT_KEYS}
    reviewed = 0
    never_analyzed = 0
    issues: list[str] = []

    for f in findings:
        ts = f.get("timestamp")
        try:
            f_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
            if f_dt is not None and f_dt.tzinfo is None:
                f_dt = f_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            f_dt = None
        if f_dt is not None and f_dt < cutoff:
            continue

        reviewed += 1
        enrichment = f.get("ai_enrichment") or {}
        ran_any = False
        for key in _SWEEP_AGENT_KEYS:
            step = enrichment.get(key)
            if not step:
                continue
            ran_any = True
            agent_run_counts[key] += 1
            if step.get("kind") == "execution_error":
                agent_error_counts[key] += 1

        if not ran_any and f_dt is not None and f_dt < stale_cutoff:
            never_analyzed += 1

    for key in _SWEEP_AGENT_KEYS:
        runs = agent_run_counts[key]
        errors = agent_error_counts[key]
        if runs >= 3 and errors / runs >= 0.5:
            issues.append(f"{key} is erroring on {errors}/{runs} recent runs -- investigate before trusting its output")

    if reviewed > 0 and never_analyzed / reviewed >= 0.2:
        issues.append(
            f"{never_analyzed}/{reviewed} findings in the last {window_hours}h were never picked up by the "
            f"synergy pipeline (older than {stale_after_minutes} min with no agent activity) -- check daemon/poller.py's "
            "_dispatch_synergy_pipeline retry loop and daemon health"
        )

    reputation_providers = []
    if os.getenv("VIRUSTOTAL_API_KEY"):
        reputation_providers.append("virustotal")
    if os.getenv("ABUSEIPDB_API_KEY"):
        reputation_providers.append("abuseipdb")
    if not reputation_providers:
        issues.append("no reputation providers configured -- Athena's verdicts will stay 'unknown' and Orion's confidence gate can never fire")

    if not issues:
        issues.append(f"no systemic issues found across {reviewed} finding(s) reviewed")

    result = ThemisSweepResult(
        kind="answered",
        swept_at=now.isoformat(),
        findings_reviewed=reviewed,
        findings_never_analyzed=never_analyzed,
        agent_run_counts=agent_run_counts,
        agent_error_counts=agent_error_counts,
        reputation_providers_configured=reputation_providers,
        systemic_issues=issues,
    )

    try:
        from database.config_service import get_config_service

        get_config_service().set_system_config(
            "themis.system_health", asdict(result),
            description="Themis's periodic multi-agent system-health sweep (capabilities/synergy.py)",
            config_type="monitoring",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Themis sweep: failed to persist result: %s", e)

    return result
