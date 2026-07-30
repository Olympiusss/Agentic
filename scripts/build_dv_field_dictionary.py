#!/usr/bin/env python3
"""Build the Deep Visibility field dictionary (Phase 2, Milestone 5, part 1).

purple_ai() was attempted for every category and failed systemically --
even the tool's own documented example question ("Is APT-1337 in my
environment?") returned the same generic error, confirmed via a live
diagnostic probe this session. This is not a phrasing problem on this
script's side; it looks like an outage or licensing gap on the tenant's
Purple AI backend. Per explicit user direction, this script falls back
to hand-composed field probes instead of the tool's documented purple_ai
-> powerquery path -- every field here is marked unverified_by_purple_ai
and every category's dictionary entry is gated experimental, never
stable, until purple_ai() is available to verify the real way.

Because a malformed/legacy field name can close the whole MCP connection
outright (confirmed in Phase 1), each category gets its own fresh
connection, and candidate fields are tested one at a time within it: a
crash only costs that category's remaining untested candidates, not the
whole run, and is recorded honestly rather than silently retried.

Run from the repo root::

    python scripts/build_dv_field_dictionary.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402

import yaml  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from scripts._sentinelone_mcp import ToolLog, call, server_params  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "dv_cookbook" / "field_dictionary.yaml"

# Conservative, generic-SentinelOne-PowerQuery-convention candidate
# fields per category. Hand-composed because purple_ai() is down --
# NOT independently confirmed against this tenant's real DV schema
# beyond what this script itself tests live. event.time and
# endpoint.name are tested for every category since they're the most
# broadly-used, lowest-risk field names; the rest are category-specific
# guesses, tested one at a time so a bad one doesn't lose the others.
CANDIDATE_FIELDS = {
    "process": ["event.time", "endpoint.name", "process.name", "process.cmdline"],
    "network": ["event.time", "endpoint.name", "dst.ip.address", "dst.port.number"],
    "dns": ["event.time", "endpoint.name", "event.dns.request"],
    "file": ["event.time", "endpoint.name", "file.path"],
    "registry": ["event.time", "endpoint.name", "registry.keyPath"],
    "login": ["event.time", "endpoint.name", "event.login.userName"],
}


async def test_category(category: str, fields: list[str]) -> dict[str, Any]:
    log = ToolLog()
    confirmed: list[str] = []
    failed_field: str | None = None
    error_text: str | None = None

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ts = await call(session, log, "get_timestamp_range", {"hours": 24}, f"24h window for {category}")
            start = ts.get("offset_time") if isinstance(ts, dict) else None
            end = ts.get("current_time") if isinstance(ts, dict) else None

            for field in fields:
                query = f'event.category = "{category}" | columns {field} | limit 1'
                try:
                    result = await call(
                        session, log, "powerquery",
                        {"query": query, "start_datetime": start, "end_datetime": end},
                        f"hand-composed probe (purple_ai unavailable): does field '{field}' exist for {category}?",
                    )
                    text = str(result)
                    if "Match Count" in text and field in text.split("Column Names:")[-1].split("\n")[0]:
                        confirmed.append(field)
                except Exception as e:  # noqa: BLE001
                    failed_field = field
                    error_text = f"{type(e).__name__}: {e}"
                    break  # connection is likely dead; stop testing this category

    return {
        "category": category,
        "purple_ai_status": "purple_ai() failed systemically this session -- confirmed via diagnostic probe using the tool's own documented example question; not a phrasing issue",
        "fields_confirmed": confirmed,
        "fields_unverified_by_purple_ai": True,
        "field_causing_connection_error": failed_field,
        "connection_error": error_text,
        "status": "experimental",
    }


async def build() -> list[dict[str, Any]]:
    entries = []
    for category, fields in CANDIDATE_FIELDS.items():
        entry = await test_category(category, fields)
        entries.append(entry)
        print(f"  {category}: confirmed={entry['fields_confirmed']} crash_field={entry['field_causing_connection_error']}")
    return entries


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries = asyncio.run(build())
    output = {
        "status": "draft_pending_review",
        "note": (
            "purple_ai() failed systemically for every category this session (confirmed via a live "
            "diagnostic probe using the tool's own documented example question, not a phrasing problem "
            "here) -- per explicit direction, this dictionary was built from hand-composed field probes "
            "instead of the tool's documented purple_ai -> powerquery path. Every entry is marked "
            "fields_unverified_by_purple_ai and gated status: experimental, never stable, until "
            "purple_ai() is available to verify these the documented way. A field name that closed the "
            "MCP connection is recorded in field_causing_connection_error rather than silently retried."
        ),
        "categories": entries,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(output, f, sort_keys=False, allow_unicode=True, width=100)
    print(f"\nWrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
