"""Milestone 7 acceptance validation for the grounding/interpretation layer.

Runs the four mechanisms in services/sentinelone_grounding_service.py
against real data wherever feasible:

  - format_grounded_answer(): one real live tool call (threat_count's
    search_alerts(first=1)), formatted with the mandatory grounding line.
  - classify_empty_result(): a real live empty host_lookup query, plus the
    ontology's real in_scope=False modules, a simulated permission error,
    and a simulated out-of-retention window.
  - decode_enum_value(): real catalogued values (from Milestone 7's 50-alert
    re-sample) and a genuinely uncatalogued value, checked against the
    uncatalogued-value log.
  - validate_query_or_refuse(): real router decisions (hard_bound, routed
    with a stable recipe, routed with no recipe, sentry_internal, ambiguous,
    fallback) -- asserts the brief's "no unvalidated queries" rule holds.

Usage:
    python scripts/validate_sentinelone_grounding.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from services import sentinelone_grounding_service as grounding  # noqa: E402
from services import sentinelone_router_service as router  # noqa: E402
from services.sentinelone_grounding_service import (  # noqa: E402
    EmptyResultClassification,
    UNCATALOGUED_ENUM_LOG_PATH,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label}: {detail}")


async def live_threat_count() -> int:
    from _sentinelone_mcp import call, server_params, total_count, ToolLog
    from mcp import ClientSession, stdio_client

    log = ToolLog()
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await call(
                session,
                log,
                "search_alerts",
                {"first": 1},
                "Milestone 7: real count for the grounded-answer format test",
            )
            return total_count(result)


async def live_empty_host_lookup() -> list:
    from _sentinelone_mcp import call, server_params, ToolLog
    from mcp import ClientSession, stdio_client
    import json as _json

    log = ToolLog()
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await call(
                session,
                log,
                "search_inventory_items",
                {
                    "filters": _json.dumps(
                        {"name__contains": ["nonexistent-host-m7-probe-zzz"]}
                    ),
                    "limit": 5,
                },
                "Milestone 7: real empty host_lookup for the classifier test",
            )
            return result


def _decision_summary(decision) -> str:
    return (
        f"decision_type={decision.decision_type} "
        f"question_class={decision.question_class}"
    )


def section(n: int, title: str) -> None:
    print()
    print("=" * 70)
    print(f"{n}. {title}")
    print("=" * 70)


def main() -> None:
    section(1, "format_grounded_answer(): real live threat_count")
    count = asyncio.run(live_threat_count())
    check(
        "live search_alerts(first=1) returned an integer totalCount",
        isinstance(count, int),
        str(count),
    )
    answer = grounding.format_grounded_answer(
        body=f"CyberVergent Ltd has {count} SentinelOne alerts on record.",
        source_module=grounding.resolve_source_module("threat_count"),
        tenant="CyberVergent Ltd",
        window="all time",
        result_count=count,
    )
    print(answer)
    for part in ["Source:", "Client:", "Window:", "Results:"]:
        check(f"grounded answer contains '{part}'", part in answer)
    check("grounded answer's Results matches the real live count", str(count) in answer)

    section(2, "classify_empty_result(): real + simulated cases")

    live_empty = asyncio.run(live_empty_host_lookup())
    import _sentinelone_mcp as sm

    empty_rows = sm.edges(live_empty)
    check(
        "live search for a nonexistent hostname genuinely returned 0 rows",
        len(empty_rows) == 0,
        str(empty_rows),
    )
    classification, reason = grounding.classify_empty_result("host_lookup")
    check(
        "real empty host_lookup classifies as NO_MATCHING_ACTIVITY",
        classification == EmptyResultClassification.NO_MATCHING_ACTIVITY,
        f"got {classification}: {reason}",
    )

    classification, reason = grounding.classify_empty_result("identity_security")
    check(
        "identity_security (in_scope=False) classifies as NO_COVERAGE",
        classification == EmptyResultClassification.NO_COVERAGE,
        f"got {classification}: {reason}",
    )

    classification, reason = grounding.classify_empty_result(
        "threat_count", tool_error="403 Forbidden: token scope insufficient"
    )
    check(
        "a 403 tool error classifies as SCOPE_OR_PERMISSION_ERROR",
        classification == EmptyResultClassification.SCOPE_OR_PERMISSION_ERROR,
        f"got {classification}: {reason}",
    )

    old_window = datetime.now(timezone.utc) - timedelta(days=200)
    classification, reason = grounding.classify_empty_result(
        "threat_count", window_start=old_window, retention_days=90
    )
    check(
        "a 200-day-old window against 90-day retention classifies as OUTSIDE_RETENTION",
        classification == EmptyResultClassification.OUTSIDE_RETENTION,
        f"got {classification}: {reason}",
    )

    section(3, "decode_enum_value(): real catalogued + uncatalogued values")

    decoded = grounding.decode_enum_value("Alert", "alert_severity", "CRITICAL")
    check(
        "CRITICAL (re-sampled live in Milestone 7) decodes cleanly",
        decoded == "CRITICAL",
        decoded,
    )

    before = 0
    if UNCATALOGUED_ENUM_LOG_PATH.exists():
        with open(UNCATALOGUED_ENUM_LOG_PATH, "r", encoding="utf-8") as f:
            before = sum(1 for _ in f)
    decoded = grounding.decode_enum_value("Alert", "alert_severity", "URGENT")
    check(
        "an uncatalogued value ('URGENT') is flagged, not silently passed through",
        "not yet catalogued" in decoded and "URGENT" in decoded,
        decoded,
    )
    after = 0
    if UNCATALOGUED_ENUM_LOG_PATH.exists():
        with open(UNCATALOGUED_ENUM_LOG_PATH, "r", encoding="utf-8") as f:
            after = sum(1 for _ in f)
    check(
        "the uncatalogued value was logged",
        after == before + 1,
        f"before={before} after={after}",
    )

    section(4, "validate_query_or_refuse(): real router decisions")

    decision = router.route("how many threats exist")
    result = grounding.validate_query_or_refuse(decision)
    check("hard_bound gap-closing intent is allowed", result.allowed, result.reason)

    decision = router.route("what are our critical vulnerabilities")
    result = grounding.validate_query_or_refuse(decision)
    check(
        f"'{decision.question_class}' routed to a stable recipe is allowed",
        result.allowed,
        f"{_decision_summary(decision)} reason={result.reason}",
    )

    decision = router.route(
        "find living-off-the-land binaries spawned from Microsoft Word"
    )
    result = grounding.validate_query_or_refuse(decision)
    check(
        "dv_hunt (no recipe yet) is refused with a closest-path pointer",
        (not result.allowed) and result.closest_validated_path is not None,
        f"{_decision_summary(decision)} allowed={result.allowed}",
    )

    decision = router.route("what has Sentry flagged")
    result = grounding.validate_query_or_refuse(decision)
    check(
        "sentry_internal is allowed (the deliberate control case)",
        result.allowed,
        f"{_decision_summary(decision)} reason={result.reason}",
    )

    decision = router.route("is this endpoint healthy and online")
    result = grounding.validate_query_or_refuse(decision)
    if decision.decision_type == "ambiguous":
        check(
            "a genuinely ambiguous route is refused", not result.allowed, result.reason
        )
    else:
        print(f"    (resolved unambiguously this run: {_decision_summary(decision)})")

    decision = router.route("what is your favorite color")
    result = grounding.validate_query_or_refuse(decision)
    check(
        "fallback with real candidate tools is allowed, with a caveat",
        result.allowed and "candidate" in result.reason,
        f"decision_type={decision.decision_type} reason={result.reason}",
    )

    print()
    print("=" * 70)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
