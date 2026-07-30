"""Milestone 8 pytest wrapper around tests/sentinelone_coverage_harness.py.

Requires live SentinelOne credentials (SENTINELONE_API_TOKEN,
SENTINELONE_CONSOLE_URL) -- skipped otherwise, same convention as the
`integration` marker's Postgres requirement (see CLAUDE.md). Not part of
the default CI `pytest --cov` run for that reason; run explicitly:

    pytest tests/test_sentinelone_coverage_matrix.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(REPO_ROOT / ".env")

from sentinelone_coverage_harness import run_harness  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.siem,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (
            os.getenv("SENTINELONE_API_TOKEN") and os.getenv("SENTINELONE_CONSOLE_URL")
        ),
        reason="requires live SENTINELONE_API_TOKEN/SENTINELONE_CONSOLE_URL",
    ),
]


@pytest.fixture(scope="module")
async def harness_report():
    return await run_harness()


async def test_regression_fixture_passes(harness_report):
    """tests/fixtures/threat_count_source.md's exact 5 pass criteria."""
    rf = harness_report.regression_fixture
    assert rf is not None
    assert rf.passed, f"regression fixture failed: {rf.criteria}"


async def test_gap_closing_set_fully_correct(harness_report):
    """Acceptance: 'the gap-closing set is fully correct on source and
    grounding' -- the brief's own non-negotiable bar for this milestone."""
    gap_closing = harness_report.gap_closing_results
    assert len(gap_closing) == 5, f"expected 5 gap-closing rows, got {len(gap_closing)}"
    failures = [r for r in gap_closing if not r.passed]
    assert (
        not failures
    ), f"gap-closing failures: {[(r.question_class, r.notes) for r in failures]}"


async def test_full_matrix_pass_rate(harness_report):
    """Acceptance: 'the agreed pass rate on the full matrix is met.' All 12
    rows, including the 5 not-yet-built ones, which pass by correctly
    refusing rather than fabricating a retrieval."""
    failures = [r for r in harness_report.results if not r.passed]
    assert (
        not failures
    ), f"matrix failures: {[(r.question_class, r.notes) for r in failures]}"


async def test_no_row_resolves_to_forbidden_source(harness_report):
    """No SentinelOne question class ever silently resolves to Sentry's
    internal findings store -- the exact failure this whole phase exists
    to fix, checked across every row, not just threat_count."""
    for r in harness_report.results:
        if r.question_class == "sentry_internal":
            continue
        assert r.source_correct, (
            f"{r.question_class} did not resolve to a correct, "
            f"non-forbidden source: {r.notes}"
        )
