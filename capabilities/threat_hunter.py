"""Threat Hunter capability (Phase 3, Milestone 3 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Runs Deep Visibility hunt templates over a stated window and aggregates
hits, tagged with each template's MITRE technique and the cookbook's own
false-positive notes.

Real constraint found while building this (not assumed): every one of the
11 templates in data/knowledge/sentinelone/dv_cookbook/ is currently
`status: experimental` -- none are `stable`. The brief's own guardrail for
this capability is explicit: "never run an experimental template without
confirmation." Rather than silently ignore that (which the single-question
dv_hunt chat path already effectively does today -- a separate, pre-
existing gap, not fixed here), this capability enforces a real
confirmation gate: called without `confirmed=True`, it returns
`kind="needs_confirmation"` naming exactly which experimental templates it
would run, and does not execute anything until the caller confirms.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DV_COOKBOOK_DIR = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "dv_cookbook"


@dataclass
class HuntHit:
    template_id: str
    hunt_pattern: str
    mitre: list[dict]
    status: str
    match_count: Optional[int]
    false_positives_observed: list
    error: Optional[str] = None


@dataclass
class ThreatHunterOutcome:
    kind: str  # "answered" | "needs_confirmation" | "execution_error"
    hits: list[HuntHit] = field(default_factory=list)
    window_label: Optional[str] = None
    pending_templates: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _all_template_ids() -> list[str]:
    return sorted(p.stem for p in DV_COOKBOOK_DIR.glob("*.yaml") if p.stem != "field_dictionary")


async def run_threat_hunter(
    window_hours: int = 24,
    template_ids: Optional[list[str]] = None,
    confirmed: bool = False,
) -> ThreatHunterOutcome:
    """Run the requested templates (or all 11 if none named) over
    `window_hours`. Refuses to execute anything experimental without
    `confirmed=True` -- returns the list of templates that would run
    instead, per the brief's own guardrail."""
    from services import sentinelone_recipe_executor as executor

    candidate_ids = template_ids or _all_template_ids()
    templates: dict[str, dict] = {}
    for tid in candidate_ids:
        tmpl = executor._load_dv_hunt_template(tid)
        if tmpl is None:
            return ThreatHunterOutcome(kind="execution_error", error=f"template '{tid}' not found")
        templates[tid] = tmpl

    experimental = [tid for tid, t in templates.items() if t.get("status") != "stable"]
    if experimental and not confirmed:
        return ThreatHunterOutcome(
            kind="needs_confirmation",
            pending_templates=experimental,
            error=(
                f"{len(experimental)} of {len(templates)} requested templates are "
                "status=experimental -- re-run with confirmed=True to proceed, or narrow "
                "template_ids to only what you've already reviewed"
            ),
        )

    window_label = f"last {window_hours} hours"
    ts, err = await executor._call("get_timestamp_range", {"hours": window_hours})
    if err:
        return ThreatHunterOutcome(kind="execution_error", error=err)
    start = ts.get("offset_time") if isinstance(ts, dict) else None
    end = ts.get("current_time") if isinstance(ts, dict) else None
    if not start or not end:
        return ThreatHunterOutcome(kind="execution_error", error="get_timestamp_range did not return a usable window")

    hits: list[HuntHit] = []
    for tid, tmpl in templates.items():
        query = tmpl.get("query_source", {}).get("resulting_query")
        result_cap = tmpl.get("result_cap")
        if not query:
            hits.append(
                HuntHit(
                    template_id=tid, hunt_pattern=tmpl.get("hunt_pattern", ""), mitre=tmpl.get("mitre", []),
                    status=tmpl.get("status", "experimental"), match_count=None,
                    false_positives_observed=tmpl.get("false_positives_observed", []),
                    error="template has no resulting_query",
                )
            )
            continue

        result, call_err = await executor._call(
            "powerquery", {"query": query, "start_datetime": start, "end_datetime": end}
        )
        if call_err:
            hits.append(
                HuntHit(
                    template_id=tid, hunt_pattern=tmpl.get("hunt_pattern", ""), mitre=tmpl.get("mitre", []),
                    status=tmpl.get("status", "experimental"), match_count=None,
                    false_positives_observed=tmpl.get("false_positives_observed", []), error=call_err,
                )
            )
            continue

        result_text = result if isinstance(result, str) else json.dumps(result)
        match_count = executor._parse_powerquery_match_count(result_text)
        # Respect the template's own result cap -- never report more hits
        # than the query itself was allowed to return.
        if match_count is not None and result_cap is not None:
            match_count = min(match_count, result_cap)
        hits.append(
            HuntHit(
                template_id=tid, hunt_pattern=tmpl.get("hunt_pattern", ""), mitre=tmpl.get("mitre", []),
                status=tmpl.get("status", "experimental"), match_count=match_count,
                false_positives_observed=tmpl.get("false_positives_observed", []),
            )
        )

    return ThreatHunterOutcome(kind="answered", hits=hits, window_label=window_label)
