"""Reporter capability (Phase 3, Milestone 6 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Assembles other capabilities' already-grounded outputs into one audit-ready
report, verbatim -- and drives session export (capabilities/session_export.py)
into PDF, DOCX, Markdown, or JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReporterOutcome:
    kind: str  # "answered" | "execution_error"
    title: str = ""
    sections: list[tuple[str, str]] = field(default_factory=list)
    error: Optional[str] = None


def assemble_report(title: str, capability_results: list[tuple[str, str]]) -> ReporterOutcome:
    """`capability_results` is an ordered list of (section_name, grounded_text).
    Composition only -- no re-summarization, no new retrieval. A section
    with empty/None text is dropped rather than included as a blank
    heading."""
    sections = [(name, text) for name, text in capability_results if text]
    if not sections:
        return ReporterOutcome(kind="execution_error", error="no capability results to assemble into a report")
    return ReporterOutcome(kind="answered", title=title, sections=sections)


async def export_report(title: str, capability_results: list[tuple[str, str]], fmt: str):
    """Assemble then export in one call -- the common case."""
    from capabilities.session_export import export_session

    outcome = assemble_report(title, capability_results)
    if outcome.kind != "answered":
        return outcome
    return export_session(title, outcome.sections, fmt)
