"""End-to-end walkthrough: question -> route (M6) -> execute recipe live ->
classify/decode/format (M7) -> grounded answer. Not a milestone deliverable
-- a standing smoke test that the M0-M7 stack actually works together
against the one connected tenant, on real questions, with real tool calls.

This is deliberately lighter than what Milestone 8's formal scored harness
will be: no accuracy scoring, no regression fixture replay, just "does the
full chain produce a correct, grounded answer right now."

Running this the first time is exactly what surfaced a real Milestone 7
correction: search_vulnerabilities/list_vulnerabilities return total_count/
page_info (snake_case), not totalCount/pageInfo (camelCase) like Alerts --
Milestones 1 and 4 checked the wrong key and concluded the tenant had only
1 vulnerability. The real total is in the tens of thousands. See
data/knowledge/sentinelone/mcp_tools.md's "Critical corrections" section.

Usage:
    python scripts/demo_sentinelone_pipeline_walkthrough.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from services import sentinelone_grounding_service as grounding  # noqa: E402
from services import sentinelone_router_service as router  # noqa: E402

TENANT = "CyberVergent Ltd"


def banner(question: str) -> None:
    print("\n" + "#" * 78)
    print(f"# QUESTION: {question}")
    print("#" * 78)


async def run_tool(session, log, tool, params, purpose):
    from _sentinelone_mcp import call

    return await call(session, log, tool, params, purpose)


async def main() -> None:
    from _sentinelone_mcp import ToolLog, edges, server_params, total_count
    from mcp import ClientSession, stdio_client

    log = ToolLog()
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ---- 1. threat_count: hard_bound, unwindowed count ----
            q = "how many threats exist"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"(confidence {decision.confidence:.3f}) recipe={decision.recipe_id}"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            result = await run_tool(session, log, "search_alerts", {"first": 1}, q)
            count = total_count(result)
            answer = grounding.format_grounded_answer(
                body=f"{TENANT} has {count} SentinelOne alerts on record.",
                source_module=grounding.resolve_source_module("threat_count"),
                tenant=TENANT,
                window="all time",
                result_count=count,
            )
            print("ANSWER:\n" + answer)

            # ---- 2. host_lookup: a real host, then a nonexistent one ----
            q = "what do we know about host <hostname>"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"recipe={decision.recipe_id}"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            sample = await run_tool(
                session,
                log,
                "list_inventory_items",
                {"limit": 1, "surface": "ENDPOINT", "fetch_fields": "MINIMAL"},
                "fetch one real hostname to look up",
            )
            # Inventory tools return {"data": [...], "pagination": {...}} --
            # a different shape than Alerts/Vulnerabilities' GraphQL edges.
            real_items = (
                sample.get("data", sample) if isinstance(sample, dict) else sample
            )
            real_name = None
            if isinstance(real_items, list) and real_items:
                real_name = real_items[0].get("name")
            print(f"(using real hostname substring: {real_name!r})")
            if real_name:
                found = await run_tool(
                    session,
                    log,
                    "search_inventory_items",
                    {
                        "filters": json.dumps({"name__contains": [real_name[:6]]}),
                        "limit": 5,
                        "fetch_fields": "MINIMAL",
                    },
                    "real host_lookup",
                )
                items = found.get("data", found) if isinstance(found, dict) else found
                n = len(items) if isinstance(items, list) else 0
                names = (
                    [i.get("name") for i in items] if isinstance(items, list) else items
                )
                answer = grounding.format_grounded_answer(
                    body=f"Found {n} endpoint(s) matching '{real_name[:6]}': {names}",
                    source_module=grounding.resolve_source_module("host_lookup"),
                    tenant=TENANT,
                    window="n/a (point lookup)",
                    result_count=n,
                )
                print("ANSWER (real host):\n" + answer)

            empty = await run_tool(
                session,
                log,
                "search_inventory_items",
                {
                    "filters": json.dumps(
                        {"name__contains": ["nonexistent-host-demo-zzz"]}
                    ),
                    "limit": 5,
                },
                "empty host_lookup",
            )
            empty_items = empty.get("data", empty) if isinstance(empty, dict) else empty
            n = len(empty_items) if isinstance(empty_items, list) else 0
            classification, reason = (
                grounding.classify_empty_result("host_lookup")
                if n == 0
                else (None, None)
            )
            answer = grounding.format_grounded_answer(
                body="No endpoints matched 'nonexistent-host-demo-zzz'.",
                source_module=grounding.resolve_source_module("host_lookup"),
                tenant=TENANT,
                window="n/a (point lookup)",
                result_count=None if n == 0 else n,
                empty_classification=classification,
                empty_reason=reason,
            )
            print("ANSWER (nonexistent host):\n" + answer)

            # ---- 3. storyline_pivot: a real storyline id ----
            q = "reconstruct the attack chain for storyline <id>"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"recipe={decision.recipe_id}"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            # Real storylineId from environment_map.yaml's sample_storyline_ids.
            storyline_id = "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"
            pivot = await run_tool(
                session,
                log,
                "search_alerts",
                {
                    "filters": json.dumps(
                        [
                            {
                                "fieldId": "storylineId",
                                "filterType": "fulltext",
                                "values": [storyline_id],
                            }
                        ]
                    ),
                    "first": 25,
                },
                "real storyline pivot",
            )
            pivot_rows = edges(pivot)
            answer = grounding.format_grounded_answer(
                body=(
                    f"Storyline {storyline_id} has {len(pivot_rows)} "
                    "alert(s) in the chain."
                ),
                source_module=grounding.resolve_source_module("storyline_pivot"),
                tenant=TENANT,
                window="all time",
                result_count=len(pivot_rows),
            )
            print("ANSWER:\n" + answer)

            # ---- 4. cve_traversal: the tenant's one real vulnerability ----
            q = "is this CVE present in our environment"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"recipe={decision.recipe_id}"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            vulns = await run_tool(
                session,
                log,
                "list_vulnerabilities",
                {"first": 1, "fields": json.dumps(["id", "cve"])},
                "fetch the tenant's one real vulnerability's CVE id",
            )
            vuln_rows = edges(vulns)
            real_cve = None
            if vuln_rows:
                cve_obj = vuln_rows[0].get("cve") or {}
                real_cve = cve_obj.get("id") if isinstance(cve_obj, dict) else None
            print(f"(using real CVE id: {real_cve!r})")
            if real_cve:
                cve_hits = await run_tool(
                    session,
                    log,
                    "search_vulnerabilities",
                    {
                        "filters": json.dumps(
                            [
                                {
                                    "fieldId": "cveId",
                                    "filterType": "string_equals",
                                    "value": real_cve,
                                }
                            ]
                        )
                    },
                    "real cve_traversal",
                )
                cve_rows = edges(cve_hits)
                answer = grounding.format_grounded_answer(
                    body=(
                        f"{real_cve} affects {len(cve_rows)} asset(s) "
                        "in this environment."
                    ),
                    source_module=grounding.resolve_source_module("cve_traversal"),
                    tenant=TENANT,
                    window="n/a (point lookup)",
                    result_count=len(cve_rows),
                )
                print("ANSWER:\n" + answer)

            # ---- 5. vulnerability_general: routed, non-gap-closing, stable recipe ----
            q = "what are our critical vulnerabilities"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"(confidence {decision.confidence:.3f}) recipe={decision.recipe_id}"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            crit = await run_tool(
                session,
                log,
                "search_vulnerabilities",
                {
                    "filters": json.dumps(
                        [
                            {
                                "fieldId": "severity",
                                "filterType": "string_equals",
                                "value": "CRITICAL",
                            }
                        ]
                    ),
                    "first": 25,
                },
                "real vulnerability_general",
            )
            crit_rows = edges(crit)
            # search_vulnerabilities returns total_count/page_info (snake_case),
            # NOT totalCount/pageInfo like Alerts (Milestone 7 correction) --
            # len(edges) alone is just this page's size, not the real total.
            real_total = crit.get("total_count") if isinstance(crit, dict) else None
            has_more = (
                (crit.get("page_info") or {}).get("has_next_page")
                if isinstance(crit, dict)
                else None
            )
            classification = reason = None
            if not crit_rows and not real_total:
                classification, reason = grounding.classify_empty_result(
                    "vulnerability_general"
                )
            if real_total:
                page_note = (
                    f" (showing first {len(crit_rows)}, more pages exist)"
                    if has_more
                    else ""
                )
                body = f"{real_total} critical vulnerabilities on record{page_note}."
            else:
                body = "No critical vulnerabilities found."
            answer = grounding.format_grounded_answer(
                body=body,
                source_module=grounding.resolve_source_module("vulnerability_general"),
                tenant=TENANT,
                window="all time",
                result_count=real_total,
                empty_classification=classification,
                empty_reason=reason,
            )
            print("ANSWER:\n" + answer)

            # ---- 6. dv_hunt: no recipe yet -- should be refused, no tool call ----
            q = "find living-off-the-land binaries spawned from Microsoft Word"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"(confidence {decision.confidence:.3f})"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            print(f"closest_validated_path: {gate.closest_validated_path}")
            print("(correctly refused -- no tool call made)")

            # ---- 7. sentry_internal: control case, not a SentinelOne call ----
            q = "what has Sentry flagged"
            banner(q)
            decision = router.route(q)
            gate = grounding.validate_query_or_refuse(decision)
            print(
                f"route: {decision.decision_type} -> {decision.question_class} "
                f"(confidence {decision.confidence:.3f})"
            )
            print(f"gate: allowed={gate.allowed} ({gate.reason})")
            print(
                "(correctly identified as Sentry-internal -- would call "
                "sentry-findings, a DIFFERENT server, not sentinelone; "
                "no SentinelOne tool call made)"
            )

    print("\n" + "=" * 78)
    print(f"Tool calls made this run: {len(log.calls)}")
    for c in log.calls:
        print(f"  - {c['tool']}({c['parameters']}) # {c['purpose']}")


if __name__ == "__main__":
    asyncio.run(main())
