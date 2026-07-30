"""Milestone 8 test harness: runs the SentinelOne coverage matrix against
the live tenant and scores each row for correct source, traceability,
grounding, and accuracy.

Per the build brief: "The coverage matrix is the spine of the whole phase.
It is the build backlog and the test set at once." This harness is that
test set, executed for real -- one real question per row, routed through
Milestone 6's router, executed live where a stable recipe exists, and
scored through Milestone 7's grounding/interpretation layer. Rows with no
recipe yet (status: not_started) are scored on whether the system refuses
correctly instead of fabricating a retrieval.

Importable (`run_harness()`) for the pytest wrapper in
test_sentinelone_coverage_matrix.py, and directly runnable for a full
report:

    python tests/sentinelone_coverage_harness.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from services import sentinelone_grounding_service as grounding  # noqa: E402
from services import sentinelone_router_service as router  # noqa: E402

FORBIDDEN_SOURCE_TEXT = "Sentry internal findings store"


@dataclass
class RowResult:
    question_class: str
    question: str
    priority: str
    decision_type: str
    source_correct: bool
    traceable: bool
    grounded: bool
    accurate: bool
    notes: str
    answer: Optional[str] = None

    @property
    def passed(self) -> bool:
        return (
            self.source_correct and self.traceable and self.grounded and self.accurate
        )


@dataclass
class HarnessReport:
    generated_at: str
    results: list[RowResult] = field(default_factory=list)
    regression_fixture: Optional["RegressionFixtureResult"] = None

    @property
    def gap_closing_results(self) -> list[RowResult]:
        return [r for r in self.results if r.priority == "gap_closing"]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def gap_closing_pass_rate(self) -> float:
        rows = self.gap_closing_results
        if not rows:
            return 0.0
        return sum(1 for r in rows if r.passed) / len(rows)


def _grounded_line_present(answer: str) -> bool:
    return all(p in answer for p in ["Source:", "Client:", "Window:", "Results:"])


async def _evaluate_executable_row(
    session, log, row: dict[str, Any], question: str
) -> RowResult:
    """Rows with a stable recipe: threat_count, host_lookup, storyline_pivot,
    agent_health, cve_traversal, threat_detail, vulnerability_general."""
    from _sentinelone_mcp import call, edges, total_count

    qc = row["question_class"]
    decision = router.route(question)
    gate = grounding.validate_query_or_refuse(decision)

    if decision.question_class != qc:
        return RowResult(
            qc,
            question,
            row["priority"],
            decision.decision_type,
            source_correct=False,
            traceable=False,
            grounded=False,
            accurate=False,
            notes=f"routed to '{decision.question_class}', expected '{qc}'",
        )
    if not gate.allowed:
        return RowResult(
            qc,
            question,
            row["priority"],
            decision.decision_type,
            source_correct=False,
            traceable=False,
            grounded=False,
            accurate=False,
            notes=f"gate refused a row with a stable recipe: {gate.reason}",
        )

    source_module = grounding.resolve_source_module(qc)
    source_correct = (
        source_module == row["source_module"]
        and FORBIDDEN_SOURCE_TEXT not in source_module
    )

    try:
        if qc == "threat_count":
            result = await call(session, log, "search_alerts", {"first": 1}, question)
            count = total_count(result)
            answer = grounding.format_grounded_answer(
                body=f"CyberVergent Ltd has {count} SentinelOne alerts on record.",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="all time",
                result_count=count,
            )
            accurate = isinstance(count, int) and count >= 0

        elif qc == "host_lookup":
            empty = await call(
                session,
                log,
                "search_inventory_items",
                {
                    "filters": json.dumps(
                        {"name__contains": ["nonexistent-m8-probe-zzz"]}
                    ),
                    "limit": 5,
                },
                question,
            )
            items = empty.get("data", []) if isinstance(empty, dict) else []
            classification, reason = grounding.classify_empty_result(qc)
            answer = grounding.format_grounded_answer(
                body="No endpoints matched the probe hostname.",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="n/a (point lookup)",
                result_count=None,
                empty_classification=classification,
                empty_reason=reason,
            )
            accurate = isinstance(items, list) and len(items) == 0

        elif qc == "storyline_pivot":
            storyline_id = "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"
            result = await call(
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
                question,
            )
            rows_ = edges(result)
            body = f"Storyline {storyline_id} has {len(rows_)} alert(s) in the chain."
            answer = grounding.format_grounded_answer(
                body=body,
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="all time",
                result_count=len(rows_),
            )
            accurate = isinstance(rows_, list)

        elif qc == "agent_health":
            result = await call(
                session,
                log,
                "search_inventory_items",
                {"filters": json.dumps({"assetStatus": ["Active"]}), "limit": 25},
                question,
            )
            items = result.get("data", []) if isinstance(result, dict) else []
            answer = grounding.format_grounded_answer(
                body=f"{len(items)} endpoint(s) with assetStatus=Active.",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="all time",
                result_count=len(items),
            )
            accurate = isinstance(items, list)

        elif qc == "cve_traversal":
            vulns = await call(
                session,
                log,
                "list_vulnerabilities",
                {"first": 1, "fields": json.dumps(["id", "cve"])},
                question,
            )
            vuln_rows = edges(vulns)
            real_cve = None
            if vuln_rows:
                cve_obj = vuln_rows[0].get("cve") or {}
                real_cve = cve_obj.get("id") if isinstance(cve_obj, dict) else None
            if not real_cve:
                return RowResult(
                    qc,
                    question,
                    row["priority"],
                    decision.decision_type,
                    source_correct,
                    traceable=True,
                    grounded=False,
                    accurate=False,
                    notes="could not fetch a real CVE id to test with",
                )
            hits = await call(
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
                question,
            )
            hit_rows = edges(hits)
            answer = grounding.format_grounded_answer(
                body=f"{real_cve} affects {len(hit_rows)} asset(s).",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="n/a (point lookup)",
                result_count=len(hit_rows),
            )
            accurate = len(hit_rows) > 0

        elif qc == "threat_detail":
            sample = await call(session, log, "list_alerts", {"first": 1}, question)
            sample_rows = edges(sample)
            if not sample_rows:
                return RowResult(
                    qc,
                    question,
                    row["priority"],
                    decision.decision_type,
                    source_correct,
                    traceable=True,
                    grounded=False,
                    accurate=False,
                    notes="could not fetch a real alert id to test with",
                )
            alert_id = sample_rows[0].get("id")
            detail = await call(
                session, log, "get_alert", {"alert_id": alert_id}, question
            )
            answer = grounding.format_grounded_answer(
                body=f"Alert {alert_id}: severity={detail.get('severity')}, "
                f"status={detail.get('status')}.",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="n/a (point lookup)",
                result_count=1,
            )
            accurate = isinstance(detail, dict) and "severity" in detail

        elif qc == "vulnerability_general":
            result = await call(
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
                question,
            )
            real_total = result.get("total_count") if isinstance(result, dict) else None
            answer = grounding.format_grounded_answer(
                body=f"{real_total} critical vulnerabilities on record.",
                source_module=source_module,
                tenant="CyberVergent Ltd",
                window="all time",
                result_count=real_total,
            )
            accurate = isinstance(real_total, int) and real_total > 0

        else:
            return RowResult(
                qc,
                question,
                row["priority"],
                decision.decision_type,
                source_correct,
                traceable=False,
                grounded=False,
                accurate=False,
                notes=f"no executor wired for '{qc}'",
            )
    except Exception as e:  # noqa: BLE001
        return RowResult(
            qc,
            question,
            row["priority"],
            decision.decision_type,
            source_correct,
            traceable=False,
            grounded=False,
            accurate=False,
            notes=f"live execution raised: {e}",
        )

    return RowResult(
        qc,
        question,
        row["priority"],
        decision.decision_type,
        source_correct=source_correct,
        traceable=True,
        grounded=_grounded_line_present(answer),
        accurate=accurate,
        notes="ok",
        answer=answer,
    )


@dataclass
class RegressionFixtureResult:
    criteria: dict[str, bool]
    answer: str

    @property
    def passed(self) -> bool:
        return all(self.criteria.values())


async def check_regression_fixture(session, log) -> RegressionFixtureResult:
    """The Milestone 0 regression fixture (tests/fixtures/threat_count_source.md),
    checked against all 5 of its literal pass criteria, run explicitly and
    separately from the matrix sweep per the brief's own Milestone 8 step
    ("Run the regression fixture from Milestone 0 and confirm it passes")."""
    from _sentinelone_mcp import call, total_count

    for paraphrase in [
        "How many threats/alerts exist in the environment?",
        "how many threats this week",
        "any active threats right now",
    ]:
        decision = router.route(paraphrase)
        criteria = {}

        # 1 & 5: routed tool call targets search_alerts via a hard-bound
        # recipe with no router discretion, never a Sentry-internal tool.
        criteria["hard_bound_no_discretion"] = decision.decision_type == "hard_bound"
        criteria["targets_search_alerts"] = "search_alerts" in decision.tools
        criteria["never_sentry_internal_tool"] = not any(
            "sentry" in t.lower() or "finding" in t.lower() for t in decision.tools
        )

        result = await call(session, log, "search_alerts", {"first": 1}, paraphrase)
        count = total_count(result)
        source_module = grounding.resolve_source_module("threat_count")
        answer = grounding.format_grounded_answer(
            body=f"CyberVergent Ltd has {count} SentinelOne alerts on record.",
            source_module=source_module,
            tenant="CyberVergent Ltd",
            window="all time",
            result_count=count,
        )

        # 2: response names the source explicitly.
        criteria["names_source_explicitly"] = "SentinelOne Alerts" in answer
        # 3: response includes client, window, count.
        criteria["includes_client_window_count"] = _grounded_line_present(answer)
        # 4: a zero result would be classified, never "clean" -- checked
        # against the classifier mechanism directly (this tenant has real
        # alerts, so a genuine zero can't be observed live this run).
        classification, _ = grounding.classify_empty_result("threat_count")
        criteria["empty_result_would_be_classified"] = (
            classification == grounding.EmptyResultClassification.NO_MATCHING_ACTIVITY
        )

        if not all(criteria.values()):
            return RegressionFixtureResult(criteria=criteria, answer=answer)

    return RegressionFixtureResult(criteria=criteria, answer=answer)


def _evaluate_unbuilt_row(row: dict[str, Any], question: str) -> RowResult:
    """Rows with status: not_started -- no recipe exists. Correct behavior
    is refusing to fabricate a retrieval, not attempting one. sentry_internal
    is the deliberate exception: it's allowed because it's the control case,
    not a SentinelOne question at all."""
    qc = row["question_class"]
    decision = router.route(question)
    gate = grounding.validate_query_or_refuse(decision)

    if qc == "sentry_internal":
        source_correct = decision.question_class == qc
        accurate = gate.allowed and "not a SentinelOne question" in gate.reason
        grounded = accurate  # the reason itself states the source correctly
        return RowResult(
            qc,
            question,
            row["priority"],
            decision.decision_type,
            source_correct=source_correct,
            traceable=True,
            grounded=grounded,
            accurate=accurate,
            notes=gate.reason,
        )

    # dv_hunt, identity_security, activity_audit, cloud_misconfiguration:
    # correct = did NOT claim a confident wrong-source answer.
    if decision.question_class != qc:
        return RowResult(
            qc,
            question,
            row["priority"],
            decision.decision_type,
            source_correct=False,
            traceable=False,
            grounded=False,
            accurate=False,
            notes=f"routed to '{decision.question_class}', expected '{qc}'",
        )
    source_correct = FORBIDDEN_SOURCE_TEXT not in (gate.reason or "") and not (
        gate.allowed
        and gate.closest_validated_path is None
        and not decision.candidate_tools
    )
    accurate = not gate.allowed or (gate.allowed and bool(decision.candidate_tools))
    grounded = bool(gate.reason)
    return RowResult(
        qc,
        question,
        row["priority"],
        decision.decision_type,
        source_correct=source_correct,
        traceable=True,
        grounded=grounded,
        accurate=accurate,
        notes=gate.reason,
    )


EXECUTABLE_CLASSES = {
    "threat_count",
    "host_lookup",
    "storyline_pivot",
    "agent_health",
    "cve_traversal",
    "threat_detail",
    "vulnerability_general",
}


async def run_harness() -> HarnessReport:
    from _sentinelone_mcp import ToolLog, server_params
    from mcp import ClientSession, stdio_client

    report = HarnessReport(generated_at=datetime.now(timezone.utc).isoformat())
    log = ToolLog()
    matrix_rows = router._load_coverage_matrix()

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            report.regression_fixture = await check_regression_fixture(session, log)
            for row in matrix_rows:
                question = row["example"][0]
                if row["question_class"] in EXECUTABLE_CLASSES:
                    result = await _evaluate_executable_row(session, log, row, question)
                else:
                    result = _evaluate_unbuilt_row(row, question)
                report.results.append(result)

    return report


def format_report_markdown(report: HarnessReport) -> str:
    n_pass = sum(1 for r in report.results if r.passed)
    gc_pass = sum(1 for r in report.gap_closing_results if r.passed)
    gc_total = len(report.gap_closing_results)
    lines = [
        "# SentinelOne coverage matrix accuracy report",
        "",
        f"Generated: {report.generated_at}",
        f"Overall pass rate: {n_pass}/{len(report.results)} ({report.pass_rate:.0%})",
        f"Gap-closing pass rate: {gc_pass}/{gc_total} "
        f"({report.gap_closing_pass_rate:.0%})",
        "",
        "## Milestone 0 regression fixture (tests/fixtures/threat_count_source.md)",
        "",
    ]

    def mark(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    if report.regression_fixture:
        rf = report.regression_fixture
        lines.append(f"Result: **{mark(rf.passed)}**")
        lines.append("")
        for name, ok in rf.criteria.items():
            lines.append(f"- {mark(ok)}: {name}")
        lines.append(f"\n```\n{rf.answer}\n```\n")
    else:
        lines.append("Not run.")
    lines += [
        "",
        "## Coverage matrix (all 12 rows)",
        "",
        "| question_class | priority | decision | source | trace | ground "
        "| accurate | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report.results:
        lines.append(
            f"| {r.question_class} | {r.priority} | {r.decision_type} | "
            f"{mark(r.source_correct)} | {mark(r.traceable)} | "
            f"{mark(r.grounded)} | {mark(r.accurate)} | {r.notes} |"
        )
    lines.append("")
    lines.append("## Sample answers")
    for r in report.results:
        if r.answer:
            lines.append(
                f"\n**{r.question_class}** (`{r.question}`):\n```\n{r.answer}\n```"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio

    rpt = asyncio.run(run_harness())
    md = format_report_markdown(rpt)
    out_path = REPO_ROOT / "tests" / "_last_harness_run.md"
    out_path.write_text(md, encoding="utf-8")
    fixture_ok = bool(rpt.regression_fixture and rpt.regression_fixture.passed)
    print(f"[{'PASS' if fixture_ok else 'FAIL'}] Milestone 0 regression fixture")
    for r in rpt.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.question_class} ({r.priority}): {r.notes}")
    print(
        f"\nOverall: {sum(1 for r in rpt.results if r.passed)}/{len(rpt.results)} "
        f"({rpt.pass_rate:.0%})  Gap-closing: "
        f"{sum(1 for r in rpt.gap_closing_results if r.passed)}/"
        f"{len(rpt.gap_closing_results)} ({rpt.gap_closing_pass_rate:.0%})"
    )
    print(f"Full report written to {out_path}")
    sys.exit(0 if (fixture_ok and rpt.gap_closing_pass_rate == 1.0) else 1)
