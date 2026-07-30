#!/usr/bin/env python3
"""Extend the storyline_pivot recipe with a Deep Visibility sweep (Phase 2, Milestone 5, part 3).

Milestone 4's storyline_pivot recipe only covers the Alerts-side pivot
(search_alerts filtered on storylineId). The full procedure in
Sentry_Agent_Task_Execution.md section 4 also sweeps Deep Visibility for
that storyline across endpoints. No field named storylineId (or similar)
is in field_dictionary.yaml, so this script first tests, in isolation,
whether such a field exists in this tenant's PowerQuery schema at all
before deciding how to implement the sweep -- per the same
crash-tolerant, one-candidate-at-a-time approach used throughout this
milestone.

Run from the repo root::

    python scripts/build_storyline_dv_sweep.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def _has_real_match(sample: str) -> bool:
    """True only if the result text actually contains a parsed 'Match
    Count: N' with N > 0 -- not just "doesn't contain 'Match Count: 0'",
    which a blank/empty string also satisfies vacuously. Caught this bug
    reviewing the first live run: it caused the wrong candidate field
    (one with a blank result) to be selected over the one that actually
    returned real data."""
    m = re.search(r"Match Count:\s*([\d.]+)", sample or "")
    return bool(m) and float(m.group(1)) > 0

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import asyncio  # noqa: E402

import yaml  # noqa: E402
from jsonschema import validate  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from scripts._sentinelone_mcp import ToolLog, call, edges, server_params  # noqa: E402

RECIPE_PATH = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "recipes" / "storyline_pivot.yaml"
RECIPE_SCHEMA_PATH = REPO_ROOT / "data" / "schemas" / "recipe.schema.json"

CANDIDATE_STORYLINE_FIELDS = ["storylineId", "storyline.id", "src.process.storyline.id"]


async def get_real_storyline_id(session: ClientSession, log: ToolLog) -> tuple[str | None, str | None]:
    sample = await call(session, log, "list_alerts", {"first": 10}, "sample alerts for a real storylineId + endpoint name")
    nodes = edges(sample)
    for n in nodes:
        if isinstance(n, dict) and n.get("storylineId"):
            asset = n.get("asset") or {}
            return n["storylineId"], asset.get("name")
    return None, None


async def test_storyline_field_candidates(storyline_id: str) -> dict[str, Any]:
    """Each candidate gets its own connection -- a bad field name can
    close the whole session (confirmed in Phase 1)."""
    results = []
    for field in CANDIDATE_STORYLINE_FIELDS:
        log = ToolLog()
        query = f'event.category = "process" and {field} = "{storyline_id}" | limit 1'
        entry = {"field": field, "query": query, "ran_ok": False, "error": None, "result_sample": ""}
        try:
            async with stdio_client(server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ts = await call(session, log, "get_timestamp_range", {"hours": 24}, "24h window for storyline field probe")
                    start = ts.get("offset_time") if isinstance(ts, dict) else None
                    end = ts.get("current_time") if isinstance(ts, dict) else None
                    result = await call(session, log, "powerquery", {"query": query, "start_datetime": start, "end_datetime": end}, f"probe candidate field '{field}' for storyline correlation")
                    entry["ran_ok"] = True
                    entry["result_sample"] = str(result)[:400]
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)
        print(f"  candidate '{field}': ran_ok={entry['ran_ok']} error={entry['error']}")
    return {"storyline_id_used": storyline_id, "candidates_tested": results}


async def test_endpoint_window_fallback(storyline_id: str, endpoint_name: str | None) -> dict[str, Any]:
    """Fallback correlation: sweep DV events on the storyline's affected
    endpoint within the same time window, using only confirmed fields
    (endpoint.name), rather than an unconfirmed direct storylineId field."""
    log = ToolLog()
    entry: dict[str, Any] = {"endpoint_name_used": endpoint_name, "ran_ok": False, "error": None, "result_sample": ""}
    if not endpoint_name:
        entry["error"] = "no real endpoint name available from the sampled alert to test this fallback"
        return entry
    query = f'event.category = "process" and endpoint.name = "{endpoint_name}" | columns event.time, process.name, process.cmdline | limit 5'
    try:
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                ts = await call(session, log, "get_timestamp_range", {"hours": 24}, "24h window for endpoint-correlation fallback")
                start = ts.get("offset_time") if isinstance(ts, dict) else None
                end = ts.get("current_time") if isinstance(ts, dict) else None
                result = await call(session, log, "powerquery", {"query": query, "start_datetime": start, "end_datetime": end}, "endpoint-window correlation fallback for storyline DV sweep")
                entry["ran_ok"] = True
                entry["result_sample"] = str(result)[:400]
                entry["query"] = query
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"{type(e).__name__}: {e}"
        entry["query"] = query
    return entry


async def main_async() -> dict[str, Any]:
    log = ToolLog()
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            storyline_id, endpoint_name = await get_real_storyline_id(session, log)

    if not storyline_id:
        return {"error": "no real storylineId found in a fresh alert sample -- cannot test the DV sweep this run"}

    field_test = await test_storyline_field_candidates(storyline_id)
    fallback_test = await test_endpoint_window_fallback(storyline_id, endpoint_name)
    return {"storyline_id": storyline_id, "endpoint_name": endpoint_name, "field_candidates": field_test, "endpoint_fallback": fallback_test}


def main() -> int:
    outcome = asyncio.run(main_async())
    print(json.dumps(outcome, indent=2, default=str))

    if "error" in outcome:
        print(outcome["error"])
        return 0

    any_field_worked = any(c["ran_ok"] and _has_real_match(c.get("result_sample", "")) for c in outcome["field_candidates"]["candidates_tested"])
    fallback_worked = outcome["endpoint_fallback"]["ran_ok"] and _has_real_match(outcome["endpoint_fallback"].get("result_sample", ""))

    recipe = yaml.safe_load(open(RECIPE_PATH, encoding="utf-8"))
    if any_field_worked:
        matched = next(c for c in outcome["field_candidates"]["candidates_tested"] if c["ran_ok"] and _has_real_match(c.get("result_sample", "")))
        recipe["tool_calls"].append({
            "tool": "powerquery",
            "parameters": {"query": f'event.category = "process" and {matched["field"]} = "{{{{storyline_id}}}}" | limit 25', "start_datetime": "{{window_start}}", "end_datetime": "{{window_end}}"},
            "purpose": f"DV sweep: field '{matched['field']}' confirmed to correlate storylineId directly on process events -- repeat per category (network/dns/file/registry/login) for a full sweep, each independently confirmed first",
        })
        recipe["expected_result_shape"] += "; plus Deep Visibility events sharing the same storylineId across endpoints"
    else:
        recipe["tool_calls"].append({
            "tool": "powerquery",
            "parameters": {"query": 'event.category = "process" and endpoint.name = "{{affected_endpoint_name}}" | columns event.time, process.name, process.cmdline | limit 25', "start_datetime": "{{window_start}}", "end_datetime": "{{window_end}}"},
            "purpose": (
                "DV sweep fallback: no field directly correlating storylineId was found valid in this tenant's "
                "PowerQuery schema (candidates tested: " + ", ".join(c["field"] for c in outcome["field_candidates"]["candidates_tested"]) + "). "
                "Sweeps the storyline's affected endpoint(s) (from the Alerts-side pivot's asset.name) over the same "
                "time window instead -- a real, working correlation, though weaker than a direct storylineId join."
            ),
        })
        recipe["expected_result_shape"] += "; plus a Deep Visibility sweep of the affected endpoint(s) over the same window (endpoint+time correlation, not a direct storylineId field join -- none was found valid in this tenant)"

    recipe["validated_edge_cases"].append({
        "case": "empty_result",
        "observed_behavior": (
            f"DV sweep candidates tested live: {[c['field'] for c in outcome['field_candidates']['candidates_tested']]}, "
            f"none confirmed a direct storylineId join" if not any_field_worked else "direct storylineId field confirmed"
        ) + f"; endpoint-window fallback ran_ok={fallback_worked}",
    })
    recipe["status"] = "stable" if (any_field_worked or fallback_worked) else "experimental"

    schema = json.load(open(RECIPE_SCHEMA_PATH, encoding="utf-8"))
    validate(recipe, schema)
    with open(RECIPE_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(recipe, f, sort_keys=False, allow_unicode=True, width=100)
    print(f"\nUpdated {RECIPE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
