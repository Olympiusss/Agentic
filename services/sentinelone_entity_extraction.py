"""Deterministic entity extraction for SentinelOne recipe inputs.

Recipes in `data/knowledge/sentinelone/recipes/` declare `{{placeholder}}`
inputs that must come from the user's free-text question. This module
extracts them with plain regex/keyword matching -- no LLM sub-call, no
guessing. Every function returns `None` when it can't find a confident
match rather than inventing one, matching the no-fabrication discipline
`services/sentinelone_grounding_service.py` and the coverage-matrix recipes
already hold themselves to. Callers must treat `None` on a *required* input
as "ask the user," never as "proceed with a default."
"""

from __future__ import annotations

import re
from typing import Optional

_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
# Longest first (SHA256 -> SHA1 -> MD5) so a 64-char hash can't accidentally
# be reported as its own 40- or 32-char substring -- \b on both ends already
# prevents this for well-formed input, but checking length-descending is the
# same defensive-first instinct as extract_cve_id/_UUID_RE elsewhere here.
_SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE)
_SHA1_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
_MD5_RE = re.compile(r"\b[0-9a-f]{32}\b", re.IGNORECASE)
_QUOTED_RE = re.compile(r"[\"']([^\"']{2,64})[\"']")
_HOSTNAME_KEYWORD_RE = re.compile(
    r"\b(?:host|hostname|endpoint|machine|device)s?\b[:\s]+([A-Za-z0-9][\w.\-]{1,63})",
    re.IGNORECASE,
)
# A bare English word ("do", "we", "online") can match the keyword pattern
# above just as easily as a real hostname -- e.g. "endpoints do we have".
# Require the captured token to actually look hostname-shaped (contains a
# digit, hyphen, underscore, or dot) before accepting it; otherwise return
# None rather than guess, per this module's own no-fabrication contract.
_HOSTNAME_SHAPE_RE = re.compile(r"[\d\-_.]")
_WINDOW_RE = re.compile(
    r"\b(?:last|past)\s+(\d+)\s*(hour|hr|day|week|month)s?\b", re.IGNORECASE
)
_WINDOW_UNIT_TO_KWARG = {
    "hour": "hours",
    "hr": "hours",
    "day": "days",
    "week": "weeks",
    "month": "months",
}
_SEVERITY_RE = re.compile(
    r"\b(CRITICAL|HIGH|MEDIUM|LOW|INFO)\b", re.IGNORECASE
)
_CONNECTIVITY_RE = re.compile(
    r"\b(offline|disconnected|not connected|connected|infected|outdated)\b",
    re.IGNORECASE,
)

_CONNECTIVITY_TO_FILTER = {
    "offline": "disconnected",
    "disconnected": "disconnected",
    "not connected": "disconnected",
    "connected": "connected",
    "infected": "infected",
    "outdated": "outdated",
}


def extract_cve_id(text: str) -> Optional[str]:
    m = _CVE_RE.search(text)
    return m.group(0).upper() if m else None


def extract_uuid(text: str) -> Optional[str]:
    m = _UUID_RE.search(text)
    return m.group(0).lower() if m else None


def extract_hash(text: str) -> Optional[str]:
    """Finds a bare MD5/SHA1/SHA256 hex string (no fabrication -- returns
    None rather than guessing, same contract as every other extractor
    here). Checked longest-first."""
    for pattern in (_SHA256_RE, _SHA1_RE, _MD5_RE):
        m = pattern.search(text)
        if m:
            return m.group(0).lower()
    return None


def extract_hostname_substring(text: str) -> Optional[str]:
    """Quoted string first (least ambiguous), else a token following an
    explicit host-referring keyword. Returns None -- never a guess -- if
    neither pattern matches; the caller must ask rather than probe blind."""
    m = _QUOTED_RE.search(text)
    if m:
        return m.group(1).strip()
    m = _HOSTNAME_KEYWORD_RE.search(text)
    if m:
        candidate = m.group(1).strip().rstrip(".,?!")
        if _HOSTNAME_SHAPE_RE.search(candidate):
            return candidate
    return None


def extract_time_window(text: str) -> Optional[tuple[str, int]]:
    """Returns (kwarg_name, amount) for `get_timestamp_range`, e.g.
    ("hours", 24) for "last 24hrs" or ("days", 7) for "last 7 days" --
    kwarg_name is exactly the parameter name the MCP tool accepts
    (data/knowledge/sentinelone/mcp_tools.md), not a generic unit label,
    so callers can pass it straight through as `**{kwarg_name: amount}`
    without a second translation step. None if no window phrase is found.
    Matches with or without a space before the unit ("24hrs" and "24 hrs"
    both match) since real users write both."""
    m = _WINDOW_RE.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    kwarg_name = _WINDOW_UNIT_TO_KWARG[m.group(2).lower()]
    return kwarg_name, amount


def extract_severity(text: str) -> Optional[str]:
    m = _SEVERITY_RE.search(text)
    return m.group(1).upper() if m else None


def extract_connectivity_filter(text: str) -> Optional[str]:
    """Best-effort keyword match for agent_health's optional connectivity
    axis. Distinct from `extract_severity`/asset-status -- this is about
    agent.networkStatus, not vulnerability severity or lifecycle state."""
    m = _CONNECTIVITY_RE.search(text)
    if not m:
        return None
    return _CONNECTIVITY_TO_FILTER.get(m.group(1).lower())
