"""Strategic-insight dashboard data (explicit user request, 2026-08-04:
"our dashboard shouldn't entirely be fe[d] with details already known or
easy to retrieve when a user logs in on SentinelOne, our dashboard
should be populated with strategic insights that would take analysts
hours, or even days to retrieve or analyze").

Deliberately reads Sentry Agentic's own internal Finding store (populated by
daemon/poller.py's SentinelOne ingestion loop + capabilities/synergy.py's
Zeus dispatch chain), not the live SentinelOne API -- this is the
distinction from services/sentinelone_dashboard_service.py, which mirrors
what any analyst can already see in the SentinelOne console in seconds.
This module surfaces what OUR OWN multi-agent analysis produced: which
findings actually had a hash/IP come back malicious (not just "there was
an alert"), cross-alert campaign clusters, and a defensible estimate of
analyst time the automation saved -- none of which exist as a single
view anywhere in SentinelOne itself.

Gracefully returns empty/zeroed sections (never fabricated numbers) when
the internal Finding store is still sparse -- the daemon poller is new
and ingestion volume grows over time, same "real data or an honest empty
state" discipline used throughout this project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Swimlane's usage-metrics dashboard (researched pattern) tracks hours
# saved per automated action. This per-finding estimate covers what Zeus's
# synergy pipeline actually automates for one finding: timeline
# reconstruction (Venus), hash/IP artifact pulls + reputation lookups
# across 2 providers (Athena), correlation sweep (Ariadne), and a
# compliance review (Themis) -- conservatively 12 minutes of analyst time
# per finding if done by hand, based on the step count, not a marketing
# number.
MINUTES_SAVED_PER_ANALYZED_FINDING = 12


@dataclass
class VerdictBreakdown:
    malicious: int = 0
    suspicious: int = 0
    clean: int = 0
    unknown: int = 0


@dataclass
class CampaignCluster:
    kind: str
    key: str
    alert_count: int
    hosts: list[str] = field(default_factory=list)


@dataclass
class PriorityFinding:
    finding_id: str
    title: str
    verdict: str
    reasoning: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    # Populated from Athena's artifact analysis (explicit user request,
    # 2026-08-05: "the respective sub agent... should investigate its
    # threat details, originating process, filepath... after which it
    # would display its findings on the strategic insights column").
    originating_process: Optional[str] = None
    file_hash: Optional[str] = None
    threat_family: Optional[str] = None


@dataclass
class BlastRadiusEntry:
    """One malicious/suspicious indicator (hash or external IP) and every
    OTHER host our own findings have seen it on -- the "what else is
    reachable/already touched" view the research pass flagged as a
    recurring pattern (Netenrich's live blast-radius panel, IBM QRadar
    Advisor's lateral-movement surfacing) that no single-alert view in
    SentinelOne's own console shows."""
    indicator: str
    indicator_kind: str  # "hash" | "ip"
    verdict: str
    origin_host: str
    origin_finding_id: str
    also_seen_on_hosts: list[str] = field(default_factory=list)


@dataclass
class StrategicInsights:
    generated_at: str
    findings_analyzed: int = 0
    verdict_breakdown: VerdictBreakdown = field(default_factory=VerdictBreakdown)
    campaign_clusters: list[CampaignCluster] = field(default_factory=list)
    top_priority_findings: list[PriorityFinding] = field(default_factory=list)
    blast_radius: list[BlastRadiusEntry] = field(default_factory=list)
    system_health: Optional[dict] = None
    estimated_hours_saved: float = 0.0
    reputation_providers_active: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _reputation_providers_active() -> list[str]:
    import os

    active = []
    if os.getenv("VIRUSTOTAL_API_KEY"):
        active.append("virustotal")
    if os.getenv("ABUSEIPDB_API_KEY"):
        active.append("abuseipdb")
    return active


def _compute_blast_radius(recent: list[dict]) -> list[BlastRadiusEntry]:
    """Reverse-indexes every process hash and external IP Athena pulled
    (capabilities/artifact_analysis.py, stored under
    ai_enrichment.athena_threat_intel) across all recent findings, then
    for each malicious/suspicious indicator reports every OTHER host it
    also showed up on -- the concrete, cross-finding question a single
    per-alert view can't answer: "is this the only host that touched
    this, or has it already spread."""
    hash_hosts: dict[str, set[str]] = {}
    ip_hosts: dict[str, set[str]] = {}
    origin_by_hash: dict[str, tuple[str, str, str]] = {}  # hash -> (verdict, host, finding_id)
    origin_by_ip: dict[str, tuple[str, str, str]] = {}

    for f in recent:
        athena = (f.get("ai_enrichment") or {}).get("athena_threat_intel") or {}
        hosts = (f.get("entity_context") or {}).get("hostnames", [])
        host = hosts[0] if hosts else "unknown host"
        finding_id = f.get("finding_id", "")

        for proc in athena.get("processes", []):
            sha = proc.get("sha256") or proc.get("sha1")
            rep = proc.get("reputation") or {}
            if not sha:
                continue
            hash_hosts.setdefault(sha, set()).add(host)
            if rep.get("verdict") in ("malicious", "suspicious") and sha not in origin_by_hash:
                origin_by_hash[sha] = (rep["verdict"], host, finding_id)

        for net in athena.get("network", []):
            ip = net.get("ip")
            rep = net.get("reputation") or {}
            if not ip:
                continue
            ip_hosts.setdefault(ip, set()).add(host)
            if rep.get("verdict") in ("malicious", "suspicious") and ip not in origin_by_ip:
                origin_by_ip[ip] = (rep["verdict"], host, finding_id)

    entries: list[BlastRadiusEntry] = []
    for sha, (verdict, host, finding_id) in origin_by_hash.items():
        others = sorted(h for h in hash_hosts.get(sha, set()) if h != host)
        entries.append(BlastRadiusEntry(
            indicator=sha[:16] + "...", indicator_kind="hash", verdict=verdict,
            origin_host=host, origin_finding_id=finding_id, also_seen_on_hosts=others,
        ))
    for ip, (verdict, host, finding_id) in origin_by_ip.items():
        others = sorted(h for h in ip_hosts.get(ip, set()) if h != host)
        entries.append(BlastRadiusEntry(
            indicator=ip, indicator_kind="ip", verdict=verdict,
            origin_host=host, origin_finding_id=finding_id, also_seen_on_hosts=others,
        ))

    # Spread (also_seen_on_hosts non-empty) is the actionable case --
    # surface those first, since a single-host indicator is lower urgency.
    entries.sort(key=lambda e: len(e.also_seen_on_hosts), reverse=True)
    return entries[:10]


def _latest_system_health() -> Optional[dict]:
    """Themis's most recent periodic sweep result (daemon/scheduler.py's
    themis_sweep task, capabilities/synergy.py's run_themis_sweep) --
    read-only here; this service never triggers a sweep itself."""
    try:
        from database.config_service import get_config_service

        return get_config_service().get_system_config("themis.system_health")
    except Exception as e:  # noqa: BLE001
        logger.debug("No Themis system health available yet: %s", e)
        return None


def get_strategic_insights(window_hours: int = 72) -> StrategicInsights:
    """Aggregates over internally-stored SentinelOne-sourced findings from
    the last `window_hours` -- never calls SentinelOne directly (that's
    services/sentinelone_dashboard_service.py's job); this reads only
    what our own pipeline already concluded."""
    from services.database_data_service import DatabaseDataService

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    try:
        svc = DatabaseDataService()
        findings = svc.get_findings(data_source="sentinelone", limit=500)
    except Exception as e:  # noqa: BLE001
        logger.error("Strategic insights: failed to load findings: %s", e)
        return StrategicInsights(generated_at=now.isoformat(), error=str(e))

    recent = []
    for f in findings:
        ts = f.get("timestamp")
        try:
            f_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
            # Finding.timestamp is a naive DateTime column -- to_dict()'s
            # isoformat() on it carries no offset, so fromisoformat parses
            # it naive. Assume UTC (everything this pipeline writes is UTC)
            # rather than compare naive vs. aware and crash.
            if f_dt is not None and f_dt.tzinfo is None:
                f_dt = f_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            f_dt = None
        if f_dt is None or f_dt >= cutoff:
            recent.append(f)

    verdict_counts = VerdictBreakdown()
    analyzed = 0
    priority: list[PriorityFinding] = []
    cluster_map: dict[str, CampaignCluster] = {}

    for f in recent:
        enrichment = f.get("ai_enrichment") or {}
        athena = enrichment.get("athena_threat_intel") or {}
        verdict = athena.get("highest_verdict")
        if verdict:
            analyzed += 1
            if verdict == "malicious":
                verdict_counts.malicious += 1
            elif verdict == "suspicious":
                verdict_counts.suspicious += 1
            elif verdict == "clean":
                verdict_counts.clean += 1
            else:
                verdict_counts.unknown += 1

            if verdict in ("malicious", "suspicious"):
                themis = enrichment.get("themis_compliance_review") or {}
                verdict_rank = {"malicious": 3, "suspicious": 2, "clean": 1}
                processes = athena.get("processes") or []
                top_process = (
                    max(processes, key=lambda p: verdict_rank.get((p.get("reputation") or {}).get("verdict"), 0))
                    if processes else None
                )
                top_rep = (top_process or {}).get("reputation") or {}
                priority.append(PriorityFinding(
                    finding_id=f.get("finding_id", ""),
                    title=f.get("description") or f.get("finding_id", ""),
                    verdict=verdict,
                    reasoning=themis.get("notes", []),
                    hosts=(f.get("entity_context") or {}).get("hostnames", []),
                    originating_process=(top_process or {}).get("process_path"),
                    file_hash=(top_process or {}).get("sha256") or (top_process or {}).get("sha1"),
                    threat_family=top_rep.get("threat_label") or top_rep.get("threat_category"),
                ))

        storyline_id = (f.get("entity_context") or {}).get("storyline_id")
        if storyline_id:
            hosts = (f.get("entity_context") or {}).get("hostnames", [])
            cluster = cluster_map.setdefault(
                storyline_id, CampaignCluster(kind="storyline", key=storyline_id, alert_count=0)
            )
            cluster.alert_count += 1
            for h in hosts:
                if h not in cluster.hosts:
                    cluster.hosts.append(h)

    campaign_clusters = [c for c in cluster_map.values() if c.alert_count > 1 or len(c.hosts) > 1]
    campaign_clusters.sort(key=lambda c: c.alert_count, reverse=True)

    priority_rank = {"malicious": 2, "suspicious": 1}
    priority.sort(key=lambda p: priority_rank.get(p.verdict, 0), reverse=True)

    return StrategicInsights(
        generated_at=now.isoformat(),
        findings_analyzed=analyzed,
        verdict_breakdown=verdict_counts,
        campaign_clusters=campaign_clusters[:10],
        top_priority_findings=priority[:10],
        blast_radius=_compute_blast_radius(recent),
        system_health=_latest_system_health(),
        estimated_hours_saved=round(analyzed * MINUTES_SAVED_PER_ANALYZED_FINDING / 60, 1),
        reputation_providers_active=_reputation_providers_active(),
    )
