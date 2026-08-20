"""Artifact reputation lookups (Phase 3 extension -- explicit user request,
2026-08-04: "upon a new threat, [the responsible subagent] should
investigate its executables such as hashes, ips against established
reputation sites like VirusTotal and AbuseIPDB and determine its
reputation score").

Deliberately NOT gated behind services.sentinelone_recipe_executor's
grounding layer -- that layer exists to stop *ungrounded SentinelOne
retrieval* answers (the router/coverage-matrix/recipe discipline). A
hash/IP reputation lookup is a direct, stateless third-party REST call
(VirusTotal's, AbuseIPDB's, and AlienVault OTX's own public APIs), not a
SentinelOne question, so it doesn't go through mcp_client at all -- no
bypass to guard against. AlienVault OTX added 2026-08-12: closes a gap
where Athena's own agent methodology (services/soc_agents.py) already
promised OTX enrichment that nothing actually queried -- tools/
alienvault_otx.py existed as an MCP tool but was never wired into the
deterministic capability-dispatch path agents actually use.

All providers gracefully no-op (kind="not_configured" / silently
skipped, per-provider) when uncredentialed, same pattern as
capabilities/notifier.py, so this module is always safe to call even
before API keys are added -- and each provider's failure is independent
of the others (one down doesn't sink the lookup, matching check_ip's
existing multi-source pattern).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

VT_BASE = "https://www.virustotal.com/api/v3"
ABUSEIPDB_BASE = "https://api.abuseipdb.com/api/v2"
OTX_BASE = "https://otx.alienvault.com/api/v1"


@dataclass
class HashReputation:
    kind: str  # "found" | "not_found" | "not_configured" | "execution_error"
    hash_value: str = ""
    malicious: int = 0
    suspicious: int = 0
    harmless: int = 0
    undetected: int = 0
    reputation_score: Optional[int] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    # Specific threat family/type (e.g. "hacktool", "trojan", "ransomware")
    # -- VirusTotal's popular_threat_classification field, confirmed live
    # 2026-08-05 against the exact hash from a real SentinelOne console
    # screenshot ("Classification: Hacktool") -- this is where that label
    # actually comes from; earlier guidance that "no more specific field
    # exists" was wrong, this field was simply never being extracted.
    threat_category: Optional[str] = None
    threat_label: Optional[str] = None
    # AlienVault OTX pulse count for this hash (number of community
    # threat-intel reports referencing it) -- reuses the exact field path
    # (`pulse_info.count`) already used by tools/alienvault_otx.py's
    # otx_check_hash MCP tool, for consistency across the two callers.
    otx_pulse_count: int = 0
    sources_checked: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def verdict(self) -> str:
        if self.kind != "found":
            return self.kind
        if self.malicious >= 5:
            return "malicious"
        # A hash VirusTotal's engines haven't flagged can still be worth
        # attention if AlienVault OTX pulses reference it -- community
        # threat-intel visibility without engine detections yet is a real
        # signal, not nothing (same "don't report clean when it isn't
        # nothing" discipline as the rest of this module).
        if self.malicious >= 1 or self.suspicious >= 3 or self.otx_pulse_count >= 3:
            return "suspicious"
        return "clean"


@dataclass
class IPReputation:
    kind: str  # "found" | "not_configured" | "execution_error"
    ip: str = ""
    abuse_confidence_score: Optional[int] = None  # AbuseIPDB 0-100
    total_reports: int = 0
    country_code: Optional[str] = None
    isp: Optional[str] = None
    vt_malicious: int = 0
    vt_suspicious: int = 0
    # AlienVault OTX pulse count for this IP -- same community-visibility
    # signal as HashReputation.otx_pulse_count above.
    otx_pulse_count: int = 0
    sources_checked: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def verdict(self) -> str:
        if self.kind != "found":
            return self.kind
        if (self.abuse_confidence_score or 0) >= 75 or self.vt_malicious >= 5:
            return "malicious"
        if (self.abuse_confidence_score or 0) >= 25 or self.vt_malicious >= 1 or self.otx_pulse_count >= 3:
            return "suspicious"
        return "clean"


async def check_hash(hash_value: str) -> HashReputation:
    """File-hash lookup against whichever of VirusTotal/AlienVault OTX are
    configured (accepts MD5/SHA1/SHA256 -- both providers resolve any of
    the three against the same indicator record). VirusTotal's
    multi-engine detection counts remain the verdict's primary source;
    OTX contributes a community pulse-count signal alongside it, same
    "additional independent source, not a replacement" role AbuseIPDB
    plays for check_ip below."""
    vt_key = os.getenv("VIRUSTOTAL_API_KEY")
    otx_key = os.getenv("ALIENVAULT_OTX_API_KEY")
    if not vt_key and not otx_key:
        return HashReputation(kind="not_configured", hash_value=hash_value)

    result = HashReputation(kind="not_found", hash_value=hash_value)
    sources: list[str] = []

    if vt_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{VT_BASE}/files/{hash_value}", headers={"x-apikey": vt_key})
            if resp.status_code != 404:
                resp.raise_for_status()
                data = resp.json().get("data", {}).get("attributes", {})
                stats = data.get("last_analysis_stats", {})
                classification = data.get("popular_threat_classification") or {}
                categories = classification.get("popular_threat_category") or []
                top_category = max(categories, key=lambda c: c.get("count", 0))["value"] if categories else None
                result.kind = "found"
                result.malicious = stats.get("malicious", 0)
                result.suspicious = stats.get("suspicious", 0)
                result.harmless = stats.get("harmless", 0)
                result.undetected = stats.get("undetected", 0)
                result.reputation_score = data.get("reputation")
                result.file_name = data.get("meaningful_name")
                result.file_type = data.get("type_description")
                result.threat_category = top_category
                result.threat_label = classification.get("suggested_threat_label")
                sources.append("virustotal")
        except Exception as e:  # noqa: BLE001
            logger.error("VirusTotal hash lookup failed for %s: %s", hash_value, e)

    if otx_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{OTX_BASE}/indicators/file/{hash_value}/general", headers={"X-OTX-API-KEY": otx_key}
                )
            if resp.status_code != 404:
                resp.raise_for_status()
                pulse_count = (resp.json().get("pulse_info") or {}).get("count", 0)
                result.otx_pulse_count = pulse_count
                if pulse_count:
                    result.kind = "found"
                sources.append("alienvault_otx")
        except Exception as e:  # noqa: BLE001
            logger.error("AlienVault OTX hash lookup failed for %s: %s", hash_value, e)

    if not sources:
        return HashReputation(kind="execution_error", hash_value=hash_value, error="all configured reputation sources failed")
    result.sources_checked = sources
    return result


async def check_ip(ip: str) -> IPReputation:
    """Checks an IP against whichever of AbuseIPDB/VirusTotal are
    configured. Only meaningful for external/public IPs -- callers should
    filter out RFC1918 private ranges before calling this (internal
    endpoint IPs have no reputation to check)."""
    vt_key = os.getenv("VIRUSTOTAL_API_KEY")
    abuse_key = os.getenv("ABUSEIPDB_API_KEY")
    otx_key = os.getenv("ALIENVAULT_OTX_API_KEY")
    if not vt_key and not abuse_key and not otx_key:
        return IPReputation(kind="not_configured", ip=ip)

    result = IPReputation(kind="found", ip=ip)
    sources: list[str] = []

    if abuse_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{ABUSEIPDB_BASE}/check",
                    params={"ipAddress": ip, "maxAgeInDays": 90},
                    headers={"Key": abuse_key, "Accept": "application/json"},
                )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            result.abuse_confidence_score = data.get("abuseConfidenceScore")
            result.total_reports = data.get("totalReports", 0)
            result.country_code = data.get("countryCode")
            result.isp = data.get("isp")
            sources.append("abuseipdb")
        except Exception as e:  # noqa: BLE001
            logger.error("AbuseIPDB lookup failed for %s: %s", ip, e)

    if vt_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{VT_BASE}/ip_addresses/{ip}", headers={"x-apikey": vt_key})
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("attributes", {})
            stats = data.get("last_analysis_stats", {})
            result.vt_malicious = stats.get("malicious", 0)
            result.vt_suspicious = stats.get("suspicious", 0)
            sources.append("virustotal")
        except Exception as e:  # noqa: BLE001
            logger.error("VirusTotal IP lookup failed for %s: %s", ip, e)

    if otx_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{OTX_BASE}/indicators/IPv4/{ip}/general", headers={"X-OTX-API-KEY": otx_key}
                )
            resp.raise_for_status()
            result.otx_pulse_count = (resp.json().get("pulse_info") or {}).get("count", 0)
            sources.append("alienvault_otx")
        except Exception as e:  # noqa: BLE001
            logger.error("AlienVault OTX IP lookup failed for %s: %s", ip, e)

    if not sources:
        return IPReputation(kind="execution_error", ip=ip, error="all configured reputation sources failed")
    result.sources_checked = sources
    return result


@dataclass
class ShodanContext:
    kind: str  # "found" | "not_found" | "not_configured" | "execution_error"
    ip: str = ""
    ports: list[int] = field(default_factory=list)
    hostnames: list[str] = field(default_factory=list)
    org: Optional[str] = None
    isp: Optional[str] = None
    vulns: list[str] = field(default_factory=list)
    error: Optional[str] = None


async def get_ip_shodan_context(ip: str) -> ShodanContext:
    """Contextual data only (explicit user request, 2026-08-18): Shodan
    doesn't produce a malicious/clean verdict the way VirusTotal/AbuseIPDB
    do -- it shows open ports, services, and known CVEs on an IP, added to
    a report as supporting context. Deliberately does NOT feed into
    check_ip()'s verdict computation.

    Same API call daemon/processor.py's own, already-working Shodan
    enrichment uses (GET /shodan/host/{ip}, confirmed live there) --
    rewritten here in this module's own async/httpx style and
    os.getenv() gating convention (matching every other provider in this
    file) rather than reused directly, since that one lives inside
    FindingProcessor's triage scoring and isn't a general-purpose
    capability other callers can import."""
    api_key = os.getenv("SHODAN_API_KEY")
    if not api_key:
        return ShodanContext(kind="not_configured", ip=ip)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://api.shodan.io/shodan/host/{ip}", params={"key": api_key})
        if resp.status_code == 404:
            return ShodanContext(kind="not_found", ip=ip)
        resp.raise_for_status()
        data = resp.json()
        return ShodanContext(
            kind="found",
            ip=ip,
            ports=data.get("ports") or [],
            hostnames=data.get("hostnames") or [],
            org=data.get("org"),
            isp=data.get("isp"),
            vulns=data.get("vulns") or [],
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Shodan lookup failed for %s: %s", ip, e)
        return ShodanContext(kind="execution_error", ip=ip, error=str(e))


@dataclass
class SandboxBehavior:
    kind: str  # "found" | "not_found" | "not_configured" | "execution_error"
    hash_value: str = ""
    # One entry per sandbox VT ran the sample through (e.g. "CAPE Sandbox") --
    # confirmed live 2026-08-06 this is a list, not a single report.
    sandbox_names: list[str] = field(default_factory=list)
    processes_created: list[str] = field(default_factory=list)
    registry_keys_opened: list[str] = field(default_factory=list)
    services_started: list[str] = field(default_factory=list)
    command_executions: list[str] = field(default_factory=list)
    mitre_technique_ids: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SimilarFiles:
    kind: str  # "found" | "not_found" | "not_configured" | "execution_error"
    hash_value: str = ""
    similar_hashes: list[str] = field(default_factory=list)
    error: Optional[str] = None


async def get_sandbox_behavior(hash_value: str) -> SandboxBehavior:
    """VirusTotal's own sandbox detonation report for a file hash --
    real dynamic-analysis IOCs (process tree, registry, network/service
    activity, MITRE techniques) without needing our own Joe Sandbox/CAPE/
    AnyRun credentials, which stay unconfigured in this environment.
    Confirmed live 2026-08-06: `GET /files/{hash}/behaviours` returns
    `{"data": [{"attributes": {...}}, ...]}`, one entry per sandbox VT
    used (id suffixed `_<Sandbox Name>`) -- fields extracted here
    (processes_created, registry_keys_opened, services_started,
    command_executions, mitre_attack_techniques) are the ones a real
    probe against a real sample actually populated; other fields VT's
    docs mention (memory_dumps, mbc, services_opened, ...) exist but
    aren't surfaced here since nothing downstream needs them yet."""
    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        return SandboxBehavior(kind="not_configured", hash_value=hash_value)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{VT_BASE}/files/{hash_value}/behaviours", headers={"x-apikey": api_key})
        if resp.status_code == 404:
            return SandboxBehavior(kind="not_found", hash_value=hash_value)
        resp.raise_for_status()
        reports = resp.json().get("data", [])
        if not reports:
            return SandboxBehavior(kind="not_found", hash_value=hash_value)

        result = SandboxBehavior(kind="found", hash_value=hash_value)
        for report in reports:
            attrs = report.get("attributes", {})
            result.sandbox_names.append(report.get("id", "").split("_", 1)[-1] or "unknown sandbox")
            result.processes_created.extend(attrs.get("processes_created", []))
            result.registry_keys_opened.extend(attrs.get("registry_keys_opened", []))
            result.services_started.extend(attrs.get("services_started", []))
            result.command_executions.extend(attrs.get("command_executions", []))
            for tech in attrs.get("mitre_attack_techniques", []):
                tid = tech.get("id")
                if tid and tid not in result.mitre_technique_ids:
                    result.mitre_technique_ids.append(tid)
        return result
    except Exception as e:  # noqa: BLE001
        logger.error("VirusTotal sandbox-behavior lookup failed for %s: %s", hash_value, e)
        return SandboxBehavior(kind="execution_error", hash_value=hash_value, error=str(e))


async def get_similar_files(hash_value: str) -> SimilarFiles:
    """VirusTotal code-similarity relationship for a file hash.

    Confirmed live 2026-08-06: `GET /files/{hash}/relationships/similar_files`
    returns 403 Forbidden ("You are not authorized to perform the
    requested operation") on this account's API tier -- this is a VT
    Intelligence (paid-tier) feature, not available on the key
    configured here. Treated as `not_configured` (same as an unset key)
    rather than `execution_error`, since retrying won't help and this
    isn't a transient failure -- if the account is ever upgraded, this
    function starts working with no caller-side change needed."""
    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        return SimilarFiles(kind="not_configured", hash_value=hash_value)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{VT_BASE}/files/{hash_value}/relationships/similar_files", headers={"x-apikey": api_key}
            )
        if resp.status_code == 403:
            return SimilarFiles(
                kind="not_configured",
                hash_value=hash_value,
                error="VirusTotal similar_files requires a VT Intelligence tier this API key doesn't have",
            )
        if resp.status_code == 404:
            return SimilarFiles(kind="not_found", hash_value=hash_value)
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            return SimilarFiles(kind="not_found", hash_value=hash_value)
        return SimilarFiles(
            kind="found",
            hash_value=hash_value,
            similar_hashes=[item.get("id") for item in items if item.get("id")],
        )
    except Exception as e:  # noqa: BLE001
        logger.error("VirusTotal similar-files lookup failed for %s: %s", hash_value, e)
        return SimilarFiles(kind="execution_error", hash_value=hash_value, error=str(e))
