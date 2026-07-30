#!/usr/bin/env python3
"""Build the 6 MITRE-tagged Deep Visibility hunt templates (Phase 2, Milestone 5, part 2).

purple_ai() failed systemically this session (confirmed via a live
diagnostic probe using the tool's own documented example question --
see build_dv_field_dictionary.py's docstring and field_dictionary.yaml).
Per explicit user direction, these templates are hand-composed from the
fields actually confirmed in field_dictionary.yaml (process.name,
process.cmdline, event.dns.request, file.path, registry.keyPath, plus
event.time/endpoint.name common to all) rather than purple_ai-generated.
Every template is gated status: experimental, never stable, until
purple_ai() is available to generate and verify these the documented
way -- this script cannot promote anything to stable.

Each template gets its own fresh MCP connection (a bad field/operator
can close the whole connection outright, confirmed in Phase 1), so a
failure on one template doesn't cost the others.

Run from the repo root::

    python scripts/build_dv_hunt_templates.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402
import json  # noqa: E402

import yaml  # noqa: E402
from jsonschema import validate  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from scripts._sentinelone_mcp import ToolLog, call, server_params  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "data" / "schemas" / "dv_template.schema.json"
OUTPUT_DIR = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "dv_cookbook"

DV_UNAVAILABLE_NOTE = (
    "purple_ai() failed systemically this session (confirmed via diagnostic probe, not a phrasing "
    "issue -- see field_dictionary.yaml). This query is hand-composed from confirmed field_dictionary.yaml "
    "fields as a fallback, per explicit user direction, and has NOT been generated or verified by "
    "purple_ai() the documented way."
)

TEMPLATES = [
    {
        "template_id": "lolbin_powershell_execution",
        "hunt_pattern": "living_off_the_land",
        "mitre": [{"tactic": "Execution", "technique_id": "T1059.001", "technique_name": "PowerShell"}],
        "natural_language_prompt": "Show me PowerShell process executions and their command lines",
        "query": 'event.category = "process" and process.name contains "powershell" | columns event.time, endpoint.name, process.name, process.cmdline | limit 5',
        "confidence_note": "process.name and process.cmdline are confirmed fields (field_dictionary.yaml); 'contains' as an operator is not independently confirmed before this run.",
    },
    {
        "template_id": "credential_access_lsass_reference",
        "hunt_pattern": "credential_access",
        "mitre": [{"tactic": "Credential Access", "technique_id": "T1003.001", "technique_name": "LSASS Memory"}],
        "natural_language_prompt": "Show me process command lines that reference lsass",
        "query": 'event.category = "process" and process.cmdline contains "lsass" | columns event.time, endpoint.name, process.name, process.cmdline | limit 5',
        "confidence_note": "Weak proxy: command-line-string matching for 'lsass' will miss most real LSASS-dumping techniques (e.g. direct memory access via a dumping tool, not a literal string reference) -- this is a coarse baseline, not a refined detector.",
    },
    {
        "template_id": "persistence_registry_run_keys",
        "hunt_pattern": "persistence",
        "mitre": [{"tactic": "Persistence", "technique_id": "T1547.001", "technique_name": "Registry Run Keys / Startup Folder"}],
        "natural_language_prompt": "Show me registry modifications to Run/RunOnce autostart keys",
        "query": 'event.category = "registry" and registry.keyPath contains "Run" | columns event.time, endpoint.name, registry.keyPath | limit 5',
        "confidence_note": "registry.keyPath is a confirmed field (field_dictionary.yaml).",
    },
    {
        "template_id": "process_injection_rundll32_proxy",
        "hunt_pattern": "process_injection",
        "mitre": [{"tactic": "Defense Evasion", "technique_id": "T1055", "technique_name": "Process Injection"}],
        "natural_language_prompt": "Show me rundll32 process executions",
        "query": 'event.category = "process" and process.name contains "rundll32" | columns event.time, endpoint.name, process.name, process.cmdline | limit 5',
        "confidence_note": "Weakest template in this set: no cross-process/API-call field was confirmed (e.g. a target-process or memory-write field), so this only proxies via a commonly-abused LOLBin name, not true injection telemetry.",
    },
    {
        "template_id": "lateral_movement_psexec_proxy",
        "hunt_pattern": "lateral_movement",
        "mitre": [{"tactic": "Lateral Movement", "technique_id": "T1021.002", "technique_name": "SMB/Windows Admin Shares"}],
        "natural_language_prompt": "Show me process command lines referencing psexec",
        "query": 'event.category = "process" and process.cmdline contains "psexec" | columns event.time, endpoint.name, process.name, process.cmdline | limit 5',
        "confidence_note": "Coarse proxy via a known lateral-movement tool name in the command line; no network-category fields were confirmed (network category returned no data in the Milestone 1/5 probe window), so a connection-based lateral-movement signal isn't available here.",
    },
    {
        "template_id": "exfiltration_dns_baseline",
        "hunt_pattern": "exfiltration",
        "mitre": [{"tactic": "Exfiltration", "technique_id": "T1048", "technique_name": "Exfiltration Over Alternative Protocol"}, {"tactic": "Command and Control", "technique_id": "T1071.004", "technique_name": "DNS"}],
        "natural_language_prompt": "Show me recent DNS requests",
        "query": 'event.category = "dns" | columns event.time, endpoint.name, event.dns.request | limit 5',
        "confidence_note": "This is a coarse DNS-activity baseline, not a refined DNS-tunneling detector -- no string-length or entropy function was confirmed in this tenant's PowerQuery dialect, which is what a real DNS-tunneling detector needs (abnormally long/high-entropy subdomains). Refinement is future work once that syntax is confirmed.",
    },
]


async def validate_one(template: dict[str, Any]) -> dict[str, Any]:
    log = ToolLog()
    result_text = ""
    error_text = None
    ran_ok = False

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ts = await call(session, log, "get_timestamp_range", {"hours": 24}, f"24h window for {template['template_id']}")
            start = ts.get("offset_time") if isinstance(ts, dict) else None
            end = ts.get("current_time") if isinstance(ts, dict) else None
            try:
                result = await call(
                    session, log, "powerquery",
                    {"query": template["query"], "start_datetime": start, "end_datetime": end},
                    f"validate hand-composed template {template['template_id']}",
                )
                result_text = str(result)
                ran_ok = True
            except Exception as e:  # noqa: BLE001
                error_text = f"{type(e).__name__}: {e}"

    return {
        "template_id": template["template_id"],
        "hunt_pattern": template["hunt_pattern"],
        "mitre": template["mitre"],
        "query_source": {
            "natural_language_prompt": template["natural_language_prompt"],
            "resulting_query": template["query"],
            "purple_ai_status": DV_UNAVAILABLE_NOTE,
            "confidence_note": template["confidence_note"],
        },
        "default_window": "PT24H",
        "result_cap": 5,
        # Left empty honestly -- no false-positive patterns were recorded
        # because no analyst triage of true vs. false positives was
        # performed this session (a single capped run's real output was
        # only checked for "did it run and return something plausible",
        # not adjudicated). See triage_status for what was actually done.
        "false_positives_observed": [],
        "triage_status": "not independently triaged this session -- ran_without_error and result_sample below are the only evidence checked",
        "status": "experimental",  # never stable without purple_ai verification
        "validation_result": {
            "ran_without_error": ran_ok,
            "error": error_text,
            "result_sample": result_text[:600],
        },
    }


async def build() -> list[dict[str, Any]]:
    results = []
    for template in TEMPLATES:
        entry = await validate_one(template)
        results.append(entry)
        print(f"  {entry['template_id']}: ran_ok={entry['validation_result']['ran_without_error']}")
    return results


def main() -> int:
    schema = json.load(open(SCHEMA_PATH, encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = asyncio.run(build())
    for entry in entries:
        # Validate against the schema minus the extra validation_result
        # diagnostic block, which isn't part of the formal template shape.
        to_validate = {k: v for k, v in entry.items() if k != "validation_result"}
        validate(to_validate, schema)
        path = OUTPUT_DIR / f"{entry['template_id']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(entry, f, sort_keys=False, allow_unicode=True, width=100)
        print(f"  wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
