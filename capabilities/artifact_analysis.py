"""Artifact & reputation analysis capability (Phase 3 extension --
explicit user request, 2026-08-04: "the responsible subagent should
investigate its executables such as hashes, ips against established
reputation sites like VirusTotal and AbuseIPDB ... examine each threat
filepath, using its originating process, threat filename and other
supporting artifacts in providing a comprehensive analysis").

Pulls real process/network artifacts for one storyline via PowerQuery
(services.sentinelone_recipe_executor._call -- the same sanctioned
direct-call path capabilities/threat_hunter.py already uses for
powerquery), then checks each distinct hash and external IP against
capabilities/reputation.py.

Field names below are live-confirmed, not assumed (artifact-reputation
build, 2026-08-04): src.process.image.{sha1,sha256,md5,path} on Process
Creation events, and src.ip.address/dst.ip.address/dst.port.number on IP
Connect events (dst.ip.address is the externally-reachable side worth a
reputation check; src.ip.address is normally the internal endpoint
itself, filtered out via _is_private_ip below).

Signed-verification fields (explicit user request, 2026-08-05: "signed
verification" as part of the SOC-analyst-style report) confirmed live
the same way: src.process.signedStatus/publisher/verifiedStatus are the
real, populated fields (e.g. "signed"/"ZOHO CORPORATION..."/"verified")
-- the equally-plausible-looking src.process.image.signedStatus and
src.process.image.publisher were tried in the same probe and came back
null for every row. Field is on src.process, not src.process.image, for
signing metadata specifically -- unlike path/hash which are under .image.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_PROCESS_QUERY = (
    'event.type = "Process Creation" AND src.process.storyline.id = "{storyline_id}" '
    "| columns event.time, endpoint.name, src.process.image.path, "
    "src.process.image.sha1, src.process.image.sha256, src.process.image.md5, "
    "src.process.signedStatus, src.process.publisher, src.process.verifiedStatus, "
    "src.process.user, src.process.parent.image.path"
)
_NETWORK_QUERY = (
    'event.type = "IP Connect" AND src.process.storyline.id = "{storyline_id}" '
    "| columns event.time, endpoint.name, event.network.direction, "
    "src.ip.address, dst.ip.address, dst.port.number, event.network.protocolName"
)

# Per-category cap on reputation lookups (live-measured, 2026-08-05): see
# the comment at its use site in analyze_storyline_artifacts for the
# rate-limit/SLA rationale.
_MAX_REPUTATION_CHECKS = 8


def _is_private_ip(ip: Optional[str]) -> bool:
    if not ip:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


@dataclass
class ProcessArtifact:
    process_path: Optional[str]
    sha1: Optional[str]
    sha256: Optional[str]
    md5: Optional[str]
    host: Optional[str]
    detected_at: Optional[int]
    # Signed-verification (explicit user request, 2026-08-05) -- SentinelOne's
    # own code-signing read on the binary, independent of VirusTotal/
    # AbuseIPDB reputation: is it signed at all, who signed it, and did
    # SentinelOne verify the signature chain. An unsigned or unverified
    # binary is itself a SOC-relevant signal even with a clean VT verdict.
    signed_status: Optional[str] = None
    publisher: Optional[str] = None
    verified_status: Optional[str] = None
    # domain\username -- confirmed live 2026-08-18 as src.process.user,
    # Windows-only in practice (see data/knowledge/sentinelone/dv_cookbook/
    # field_dictionary.yaml's process_user_field note); None on Linux/macOS.
    process_user: Optional[str] = None
    # Originating/parent process path (explicit user request, 2026-08-18:
    # the investigative-report template's "Originating Process" field).
    # src.process.parent.image.path mirrors the confirmed src.process.image.path
    # naming convention but was NOT independently live-verified this session
    # (probe attempts against historical storylines timed out) -- degrades to
    # None/"not available" rather than fabricate; will get its first real
    # confirmation the next time a live alert flows through this query.
    parent_process_path: Optional[str] = None
    reputation: Optional[dict] = None  # HashReputation as dict, filled in if VT configured

    @property
    def file_name(self) -> Optional[str]:
        """Filename broken out of the full path (explicit user request,
        2026-08-05: report filename separately from filepath)."""
        if not self.process_path:
            return None
        return self.process_path.replace("/", "\\").rsplit("\\", 1)[-1]


@dataclass
class NetworkArtifact:
    dst_ip: str
    dst_port: Optional[int]
    protocol: Optional[str]
    host: Optional[str]
    reputation: Optional[dict] = None  # IPReputation as dict, filled in if configured
    # Contextual only (explicit user request, 2026-08-18) -- open ports/
    # org/known CVEs on this IP, ShodanContext as dict. Never factors into
    # `reputation`'s verdict; purely supporting context for the report.
    shodan: Optional[dict] = None


@dataclass
class ArtifactAnalysisOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error"
    storyline_id: Optional[str] = None
    processes: list[ProcessArtifact] = field(default_factory=list)
    network_connections: list[NetworkArtifact] = field(default_factory=list)
    highest_verdict: str = "unknown"  # "malicious" | "suspicious" | "clean" | "unknown"
    reputation_sources_used: list[str] = field(default_factory=list)
    # Athena's actual analyst write-up, not just structured data (explicit
    # user request, 2026-08-05: "it should not just state but conduct and
    # carry out a thorough threat intel specialist investigation and
    # analysis, explaining the processes, what is happening exactly").
    # None when synthesis fails/is unavailable -- callers fall back to the
    # structured fields, never block on this.
    narrative: Optional[str] = None
    error: Optional[str] = None


_VERDICT_RANK = {"malicious": 3, "suspicious": 2, "clean": 1, "unknown": 0, "not_configured": 0, "not_found": 0, "execution_error": 0}


async def analyze_storyline_artifacts(storyline_id: str, window_hours: int = 24) -> ArtifactAnalysisOutcome:
    """Pull process/network artifacts for a storyline and score each
    distinct hash/external IP against configured reputation providers.
    Never raises -- a reputation-provider failure degrades that one
    artifact's `reputation` to None rather than failing the whole
    analysis (artifacts themselves are still real, retrieved data)."""
    from services import sentinelone_recipe_executor as executor
    from capabilities import reputation

    ts, err = await executor._call("get_timestamp_range", {"hours": window_hours})
    if err:
        return ArtifactAnalysisOutcome(kind="execution_error", storyline_id=storyline_id, error=err)
    start = ts.get("offset_time") if isinstance(ts, dict) else None
    end = ts.get("current_time") if isinstance(ts, dict) else None
    if not start or not end:
        return ArtifactAnalysisOutcome(
            kind="execution_error", storyline_id=storyline_id, error="get_timestamp_range did not return a usable window"
        )

    # Process and network queries are independent of each other -- run
    # concurrently, not sequentially (explicit user request, 2026-08-05: a
    # full investigative report must go out within 3 minutes of the alert;
    # a single PowerQuery call live-measured at ~15-30s in this
    # environment, so two of them back-to-back is real, avoidable latency
    # against that budget).
    (proc_result, proc_err), (net_result, net_err) = await asyncio.gather(
        executor._call(
            "powerquery",
            {"query": _PROCESS_QUERY.format(storyline_id=storyline_id), "start_datetime": start, "end_datetime": end},
        ),
        executor._call(
            "powerquery",
            {"query": _NETWORK_QUERY.format(storyline_id=storyline_id), "start_datetime": start, "end_datetime": end},
        ),
    )
    if proc_err:
        return ArtifactAnalysisOutcome(kind="execution_error", storyline_id=storyline_id, error=proc_err)
    if net_err:
        # Process artifacts are still useful on their own -- degrade, don't fail.
        logger.warning("Network artifact query failed for storyline %s: %s", storyline_id, net_err)
        net_result = ""

    proc_text = proc_result if isinstance(proc_result, str) else str(proc_result)
    net_text = net_result if isinstance(net_result, str) else str(net_result)

    proc_rows = executor._parse_powerquery_rows(proc_text)
    net_rows = executor._parse_powerquery_rows(net_text)

    # Dedup by sha256 (fall back to sha1) -- the same executable often
    # appears across multiple process-creation events in one storyline.
    seen_hashes: dict[str, ProcessArtifact] = {}
    for row in proc_rows:
        sha256 = row.get("src.process.image.sha256")
        sha1 = row.get("src.process.image.sha1")
        key = sha256 or sha1
        if not key or key in seen_hashes:
            continue
        seen_hashes[key] = ProcessArtifact(
            process_path=row.get("src.process.image.path"),
            sha1=sha1,
            sha256=sha256,
            md5=row.get("src.process.image.md5"),
            host=row.get("endpoint.name"),
            detected_at=row.get("event.time"),
            signed_status=row.get("src.process.signedStatus"),
            publisher=row.get("src.process.publisher"),
            verified_status=row.get("src.process.verifiedStatus"),
            process_user=row.get("src.process.user"),
            parent_process_path=row.get("src.process.parent.image.path"),
        )

    seen_ips: dict[str, NetworkArtifact] = {}
    for row in net_rows:
        dst_ip = row.get("dst.ip.address")
        if not dst_ip or _is_private_ip(dst_ip) or dst_ip in seen_ips:
            continue
        seen_ips[dst_ip] = NetworkArtifact(
            dst_ip=dst_ip,
            dst_port=row.get("dst.port.number"),
            protocol=row.get("event.network.protocolName"),
            host=row.get("endpoint.name"),
        )

    highest_verdict = "unknown"
    sources_used: set[str] = set()

    # Reputation checks are independent per-artifact HTTP calls -- fired
    # concurrently, not one at a time, for the same 3-minute-SLA reason the
    # two PowerQuery calls above were parallelized. VirusTotal resolves
    # MD5/SHA1/SHA256 to the identical file record (confirmed in
    # capabilities/reputation.py's own docstring), so one lookup per file
    # using its strongest available hash is correct -- not a gap against
    # "check all hash types"; the SOC-analyst deliverable is showing all
    # three hash values for cross-referencing against other tools, which
    # ProcessArtifact already carries (sha1/sha256/md5 all captured above).
    #
    # Capped at _MAX_REPUTATION_CHECKS per category (live-measured,
    # 2026-08-05): a single busy storyline (10 distinct hashes + 13
    # external IPs = ~23 lookups) took 145s for reputation checks alone,
    # almost certainly VirusTotal's public-tier rate limit (4 req/min)
    # throttling a burst this size -- dangerously close to blowing the
    # explicit 3-minute investigative-report SLA on its own. Checking the
    # first N (by DV event order, i.e. earliest-seen first) keeps
    # worst-case latency bounded and covers the overwhelming majority of
    # real alerts, which involve far fewer than 8 distinct executables/
    # IPs in their immediate causal chain. Never silent -- logs when
    # truncation actually happens.
    hash_artifacts = list(seen_hashes.values())
    ip_artifacts = list(seen_ips.values())
    if len(hash_artifacts) > _MAX_REPUTATION_CHECKS:
        logger.warning(
            "storyline %s: %d distinct hashes found, only checking the first %d against VirusTotal "
            "(rate-limit/SLA guard) -- remaining artifacts still listed but unscored",
            storyline_id, len(hash_artifacts), _MAX_REPUTATION_CHECKS,
        )
    if len(ip_artifacts) > _MAX_REPUTATION_CHECKS:
        logger.warning(
            "storyline %s: %d distinct external IPs found, only checking the first %d against "
            "AbuseIPDB/VirusTotal (rate-limit/SLA guard) -- remaining artifacts still listed but unscored",
            storyline_id, len(ip_artifacts), _MAX_REPUTATION_CHECKS,
        )
    checked_hashes = hash_artifacts[:_MAX_REPUTATION_CHECKS]
    checked_ips = ip_artifacts[:_MAX_REPUTATION_CHECKS]
    hash_reps, ip_reps, shodan_reps = await asyncio.gather(
        asyncio.gather(*(reputation.check_hash(a.sha256 or a.sha1 or a.md5 or "") for a in checked_hashes)),
        asyncio.gather(*(reputation.check_ip(a.dst_ip) for a in checked_ips)),
        # Contextual only (explicit user request, 2026-08-18) -- fired in
        # the same parallel gather as check_ip, not sequentially after, so
        # it doesn't add its own latency against the 3-minute SLA.
        asyncio.gather(*(reputation.get_ip_shodan_context(a.dst_ip) for a in checked_ips)),
    )
    hash_artifacts, ip_artifacts = checked_hashes, checked_ips

    for artifact, rep in zip(hash_artifacts, hash_reps):
        artifact.reputation = {
            "kind": rep.kind, "verdict": rep.verdict, "malicious": rep.malicious,
            "suspicious": rep.suspicious, "reputation_score": rep.reputation_score,
            "threat_category": rep.threat_category, "threat_label": rep.threat_label,
            "otx_pulse_count": rep.otx_pulse_count,
        }
        sources_used.update(rep.sources_checked)
        if _VERDICT_RANK.get(rep.verdict, 0) > _VERDICT_RANK.get(highest_verdict, 0):
            highest_verdict = rep.verdict

    for artifact, rep in zip(ip_artifacts, ip_reps):
        artifact.reputation = {
            "kind": rep.kind, "verdict": rep.verdict, "abuse_confidence_score": rep.abuse_confidence_score,
            "total_reports": rep.total_reports, "vt_malicious": rep.vt_malicious,
            "otx_pulse_count": rep.otx_pulse_count,
        }
        sources_used.update(rep.sources_checked)
        if _VERDICT_RANK.get(rep.verdict, 0) > _VERDICT_RANK.get(highest_verdict, 0):
            highest_verdict = rep.verdict

    for artifact, shodan_ctx in zip(ip_artifacts, shodan_reps):
        if shodan_ctx.kind == "found":
            artifact.shodan = {
                "ports": shodan_ctx.ports, "org": shodan_ctx.org, "isp": shodan_ctx.isp,
                "hostnames": shodan_ctx.hostnames, "vulns": shodan_ctx.vulns,
            }

    narrative = await _synthesize_narrative(
        storyline_id, list(seen_hashes.values()), list(seen_ips.values()), highest_verdict, sorted(sources_used)
    )

    return ArtifactAnalysisOutcome(
        kind="answered",
        storyline_id=storyline_id,
        processes=list(seen_hashes.values()),
        network_connections=list(seen_ips.values()),
        highest_verdict=highest_verdict,
        reputation_sources_used=sorted(sources_used),
        narrative=narrative,
    )


_NARRATIVE_INSTRUCTIONS = """You are Athena <Threat Intel>, a SOC threat intelligence analyst. Adopt the same investigative mindset a human SOC analyst uses working a new alert (explicit standard, 2026-08-05): lead with Deep Visibility as the originating, ground-truth data source, cross-reference every artifact against established threat-intel sources, and reason about the FULL artifact profile, not just a hash lookup -- originating process, executable/filename, filepath, and code-signing status all matter to the verdict, not just a VirusTotal score.

Write a genuine investigative analysis of what was found -- not a template, not a restatement of the raw data below, an actual analyst's write-up explaining the process and the significance.

Ground every claim in the retrieved evidence below -- never invent a hash, IP, process, publisher, or verdict not present in it. If the evidence is thin (e.g. no artifacts found, or reputation providers unconfigured), say that plainly rather than padding the analysis.

Structure your answer as:

METHODOLOGY:
1-2 sentences on what was actually done: pulled process-creation and network-connection events tied to this storyline via SentinelOne's Deep Visibility (PowerQuery) -- the originating source for every artifact below -- then cross-referenced every distinct file hash and external IP against whichever of VirusTotal (multi-engine detections, threat-family classification), AbuseIPDB (abuse confidence), and AlienVault OTX (community pulse count) are configured -- state plainly which of the three actually returned data (see "Reputation sources actually queried" below), never imply a source was checked when it wasn't.

FINDINGS:
Walk through what was actually found -- which processes ran (name the executable/filename and filepath, not just a hash), their full hash set, code-signing status (signed/unsigned, publisher, SentinelOne's verification result) and reputation, which external hosts were contacted and their reputation, in plain analytical language (not a re-dump of the table below). Name specific hashes/IPs/processes when they matter, and their exact threat family if VirusTotal identified one (e.g. "hacktool", "trojan"). A nonzero OTX pulse count on an artifact VirusTotal itself scored clean is still worth naming -- community threat-intel visibility without engine detections yet, not nothing. An unsigned or unverified binary is a signal worth calling out even when reputation comes back clean -- reputation and code-signing are separate checks, not substitutes for each other.

ASSESSMENT:
What this means: is this storyline benign, suspicious, or malicious activity, and why -- reference the specific evidence that drives that conclusion (reputation AND signing status together). If nothing stood out, say so and explain why (e.g. "all N observed processes are common, signed system/application binaries with no VirusTotal detections").

Retrieved evidence for storyline {storyline_id}:

Process artifacts ({process_count}):
{process_block}

Network artifacts ({network_count}):
{network_block}

Reputation sources actually queried: {sources}
"""


async def _synthesize_narrative(
    storyline_id: str,
    processes: list[ProcessArtifact],
    network_connections: list[NetworkArtifact],
    highest_verdict: str,
    sources_used: list[str],
) -> Optional[str]:
    """Best-effort -- returns None (never raises) on any synthesis
    failure, so a down LLM gateway degrades this to "no narrative
    available" rather than failing the whole artifact analysis."""
    if not processes and not network_connections:
        return None

    process_block = "\n".join(
        f"- filename={p.file_name or 'unknown'} | filepath={p.process_path or 'unknown path'} | host={p.host or 'unknown host'} | "
        f"sha256={p.sha256 or 'n/a'} | sha1={p.sha1 or 'n/a'} | md5={p.md5 or 'n/a'} | "
        f"signed_status={p.signed_status or 'unknown'} | publisher={p.publisher or 'n/a'} | verified_status={p.verified_status or 'unknown'} | "
        f"reputation={(p.reputation or {}).get('verdict', 'unknown')} | "
        f"threat_family={(p.reputation or {}).get('threat_label') or (p.reputation or {}).get('threat_category') or 'n/a'} | "
        f"VT detections: {(p.reputation or {}).get('malicious', 0)} malicious / {(p.reputation or {}).get('suspicious', 0)} suspicious | "
        f"OTX pulses: {(p.reputation or {}).get('otx_pulse_count', 0)}"
        for p in processes
    ) or "(none found)"

    network_block = "\n".join(
        f"- {n.dst_ip}:{n.dst_port or '?'} ({n.protocol or 'unknown protocol'}) from {n.host or 'unknown host'} | "
        f"reputation={(n.reputation or {}).get('verdict', 'unknown')} | "
        f"AbuseIPDB confidence={(n.reputation or {}).get('abuse_confidence_score', 'n/a')} | "
        f"VT malicious detections={(n.reputation or {}).get('vt_malicious', 0)} | "
        f"OTX pulses={(n.reputation or {}).get('otx_pulse_count', 0)}"
        for n in network_connections
    ) or "(none found)"

    prompt = _NARRATIVE_INSTRUCTIONS.format(
        storyline_id=storyline_id,
        process_count=len(processes),
        process_block=process_block,
        network_count=len(network_connections),
        network_block=network_block,
        sources=", ".join(sources_used) or "none configured",
    )

    from capabilities.synthesis import synthesize

    text, err = await synthesize(prompt, agent_id="threat_intel")
    if err:
        logger.warning("Athena narrative synthesis failed for storyline %s: %s", storyline_id, err)
        return None
    return text
