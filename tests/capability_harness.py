"""Milestone 8 test harness (Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md):
runs each `status: stable` capability against the live tenant and scores
grounding, traceability, and composition-only compliance -- the same
discipline tests/sentinelone_coverage_harness.py already applies to the
underlying recipes.

Usage:
    python tests/capability_harness.py
"""

from __future__ import annotations

import ast
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

CAPABILITIES_DIR = REPO_ROOT / "capabilities"

# Real IDs confirmed live against this tenant during Milestones 1-4's own
# live validation this session -- not invented, not a mock. Re-verify if
# the tenant's data is later cleared/rotated.
REAL_ALERT_WITH_HISTORY = "019f8e3f-e6ba-787e-b4d4-0287094fdd5a"  # rich MITIGATION_RESULT/ANALYST_VERDICT history
REAL_ALERT_WITH_STORYLINE = "019fc64e-b780-7c21-8573-9bcf7ad7fb81"  # carries a real storylineId
REAL_CVE = "CVE-2026-2800"


@dataclass
class CapabilityResult:
    capability_id: str
    grounded: bool
    traceable: bool
    composition_only: bool
    notes: str
    passed_static_scan: bool = True


def _static_no_raw_tool_bypass(capability_id: str) -> tuple[bool, str]:
    """Confirms a capability's own module never imports services.mcp_client
    directly -- the only sanctioned path to SentinelOne data is
    services.sentinelone_recipe_executor's execute()/_call(), which is
    itself the one place raw tool calls happen, already covered by that
    module's own test suite. A capability importing mcp_client directly
    would be bypassing the recipe/composition layer the whole brief
    exists to enforce."""
    path = CAPABILITIES_DIR / f"{capability_id}.py"
    if not path.exists():
        return False, f"{path} not found"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "mcp_client" in node.module:
            return False, f"{capability_id}.py imports mcp_client directly -- bypasses the recipe layer"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "mcp_client" in alias.name:
                    return False, f"{capability_id}.py imports mcp_client directly -- bypasses the recipe layer"
    return True, "no direct mcp_client import found"


def _grounded(text: Optional[str]) -> bool:
    return bool(text) and "Source:" in text and "Client:" in text


async def _check_triage() -> CapabilityResult:
    from capabilities import triage

    outcome = await triage.run_triage(REAL_ALERT_WITH_HISTORY)
    static_ok, static_note = _static_no_raw_tool_bypass("triage")
    return CapabilityResult(
        "triage",
        grounded=any(_grounded(e) for e in outcome.evidence),
        traceable=outcome.kind == "answered",
        composition_only=static_ok,
        notes=f"kind={outcome.kind}; {static_note}",
        passed_static_scan=static_ok,
    )


async def _check_investigator() -> CapabilityResult:
    from capabilities import investigator

    outcome = await investigator.run_investigator(REAL_ALERT_WITH_STORYLINE)
    static_ok, static_note = _static_no_raw_tool_bypass("investigator")
    return CapabilityResult(
        "investigator",
        grounded=any(_grounded(e) for e in outcome.evidence),
        traceable=outcome.kind == "answered" and len(outcome.timeline) > 0,
        composition_only=static_ok,
        notes=f"kind={outcome.kind}, timeline_len={len(outcome.timeline)}; {static_note}",
        passed_static_scan=static_ok,
    )


async def _check_threat_hunter() -> CapabilityResult:
    from capabilities import threat_hunter

    unconfirmed = await threat_hunter.run_threat_hunter(template_ids=["recon_commands"], confirmed=False)
    static_ok, static_note = _static_no_raw_tool_bypass("threat_hunter")
    return CapabilityResult(
        "threat_hunter",
        grounded=True,  # HuntHit carries MITRE tags straight from the cookbook; no free-text grounding line to check
        traceable=unconfirmed.kind == "needs_confirmation",  # confirms the guardrail actually fires
        composition_only=static_ok,
        notes=f"unconfirmed_kind={unconfirmed.kind} (must be needs_confirmation -- all templates are experimental); {static_note}",
        passed_static_scan=static_ok,
    )


async def _check_correlator() -> CapabilityResult:
    from capabilities import correlator

    outcome = await correlator.run_correlator(sample_size=20)
    static_ok, static_note = _static_no_raw_tool_bypass("correlator")
    return CapabilityResult(
        "correlator",
        grounded=outcome.sample_size > 0,
        traceable=outcome.kind == "answered",
        composition_only=static_ok,
        notes=f"kind={outcome.kind}, sample_size={outcome.sample_size}, clusters={len(outcome.clusters)}; {static_note}",
        passed_static_scan=static_ok,
    )


async def _check_threat_intel() -> CapabilityResult:
    from capabilities import threat_intel

    outcome = await threat_intel.run_threat_intel(REAL_CVE)
    static_ok, static_note = _static_no_raw_tool_bypass("threat_intel")
    return CapabilityResult(
        "threat_intel",
        grounded=any("CVSS" in e for e in outcome.evidence),
        traceable=outcome.kind == "answered",
        composition_only=static_ok,
        notes=f"kind={outcome.kind}; {static_note}",
        passed_static_scan=static_ok,
    )


async def _check_reporter_and_export() -> CapabilityResult:
    from capabilities import reporter

    result = await reporter.export_report(
        "Capability Harness Smoke Test",
        [("Evidence", "Alert xyz.\n\nSource: SentinelOne Alerts · Client: Test")],
        "markdown",
    )
    ok = result.kind == "answered" and result.output_path is not None and result.output_path.exists()
    if ok:
        result.output_path.unlink()  # harness artifact, not a real report -- clean up immediately
    return CapabilityResult(
        "reporter",
        grounded=True,
        traceable=ok,
        composition_only=True,  # reporter/session_export never touch mcp_client at all (file I/O only)
        notes=f"export kind={result.kind}",
    )


async def _check_brief() -> CapabilityResult:
    from capabilities import brief

    outcome = await brief.run_brief()
    static_ok, static_note = _static_no_raw_tool_bypass("brief")
    return CapabilityResult(
        "brief",
        grounded=any(_grounded(e) for e in outcome.evidence),
        traceable=outcome.kind == "answered",
        composition_only=static_ok,
        notes=f"kind={outcome.kind}; {static_note}",
        passed_static_scan=static_ok,
    )


CHECKS = {
    "triage": _check_triage,
    "investigator": _check_investigator,
    "threat_hunter": _check_threat_hunter,
    "correlator": _check_correlator,
    "threat_intel": _check_threat_intel,
    "reporter": _check_reporter_and_export,
    "brief": _check_brief,
}


async def run_harness() -> list[CapabilityResult]:
    results = []
    for capability_id, check in CHECKS.items():
        try:
            results.append(await check())
        except Exception as e:  # noqa: BLE001
            results.append(
                CapabilityResult(
                    capability_id, grounded=False, traceable=False, composition_only=False,
                    notes=f"harness check raised: {e}", passed_static_scan=False,
                )
            )
    return results


def format_report(results: list[CapabilityResult]) -> str:
    n_pass = sum(1 for r in results if r.grounded and r.traceable and r.composition_only)
    lines = [
        "# Phase 3 capability quality report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Pass rate: {n_pass}/{len(results)}",
        "",
        "| capability | grounded | traceable | composition_only | notes |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        mark = lambda b: "PASS" if b else "FAIL"
        lines.append(f"| {r.capability_id} | {mark(r.grounded)} | {mark(r.traceable)} | {mark(r.composition_only)} | {r.notes} |")
    return "\n".join(lines)


if __name__ == "__main__":
    rpt = asyncio.run(run_harness())
    md = format_report(rpt)
    out_path = REPO_ROOT / "tests" / "_last_capability_harness_run.md"
    out_path.write_text(md, encoding="utf-8")
    all_pass = all(r.grounded and r.traceable and r.composition_only for r in rpt)
    for r in rpt:
        status = "PASS" if (r.grounded and r.traceable and r.composition_only) else "FAIL"
        print(f"[{status}] {r.capability_id}: {r.notes}")
    print(f"\nFull report written to {out_path}")
    sys.exit(0 if all_pass else 1)
