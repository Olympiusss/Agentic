"""Grounding and interpretation layer for SentinelOne answers.

Phase 2, Milestone 7. Implements the mechanical, testable half of
`data/agent/protocol/task_execution_protocol.md` (the operating contract
Milestone 6's router output feeds into): the answer-format contract, the
empty-result classifier, enum decoding, and the refusal/validation gate.
These are deterministic Python functions, not prompt suggestions -- the
router already proved (Milestone 6) that "trust the model to follow the
rule" is exactly the failure mode this phase exists to fix.

Consumers: the (not-yet-built) capabilities-phase agent loop calls
`validate_query_or_refuse()` on a `RouteDecision` before executing anything,
then `format_grounded_answer()` on the result. Milestone 8's test harness
calls all four functions directly against real recipe executions to score
grounding/traceability.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from services.sentinelone_recipe_library import get_recipe_by_intent
from services.sentinelone_router_service import RouteDecision, _load_coverage_matrix

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_ROOT = REPO_ROOT / "data" / "knowledge" / "sentinelone"
ONTOLOGY_PATH = KNOWLEDGE_ROOT / "ontology" / "sentinelone_ontology.yaml"
PROTOCOL_PATH = REPO_ROOT / "data" / "agent" / "protocol" / "task_execution_protocol.md"
INTERPRETATION_DIR = KNOWLEDGE_ROOT / "interpretation"
UNCATALOGUED_ENUM_LOG_PATH = INTERPRETATION_DIR / "uncatalogued_enum_values.jsonl"

SENTRY_INTERNAL_QUESTION_CLASS = "sentry_internal"

# Confirmed by direct inventory scan of the 33 tools in mcp_tools.md
# (Milestone 7): every tool is get_/list_/search_/cve_/powerquery/
# purple_ai/threat_intel_/timestamp-prefixed. No isolate/mitigate/
# quarantine/policy-change tool exists in this server's surface at all --
# the read-only guardrail is structural, not just a prompt instruction.
READ_ONLY_GUARDRAIL_NOTE = (
    "No mutating tool exists in the sentinelone MCP server's 33-tool "
    "inventory (confirmed by direct scan, Milestone 7) -- read-only "
    "operation is enforced by the tool surface itself, not just policy."
)

_PERMISSION_ERROR_PATTERN = re.compile(
    r"permission|forbidden|unauthoriz|access denied|invalid.?token|401|403",
    re.IGNORECASE,
)


class EmptyResultClassification(str, Enum):
    NO_MATCHING_ACTIVITY = "no_matching_activity"
    OUTSIDE_RETENTION = "outside_retention"
    NO_COVERAGE = "no_coverage"
    SCOPE_OR_PERMISSION_ERROR = "scope_or_permission_error"


@dataclass
class RefusalGateResult:
    allowed: bool
    reason: str
    closest_validated_path: Optional[str] = None


def load_protocol_text() -> str:
    """The task execution protocol -- the operating contract. Load this
    verbatim wherever the full contract needs to be shown; the functions in
    this module implement its mechanical rules (sections 1, 4-7)."""
    return PROTOCOL_PATH.read_text(encoding="utf-8")


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _load_ontology_entities() -> dict[str, dict]:
    data = _read_yaml(ONTOLOGY_PATH)
    return {e["entity"]: e for e in data.get("entities", [])}


@lru_cache(maxsize=1)
def _load_matrix_rows_by_class() -> dict[str, dict]:
    return {r["question_class"]: r for r in _load_coverage_matrix()}


def resolve_source_module(question_class: str) -> str:
    row = _load_matrix_rows_by_class().get(question_class)
    if row is None:
        raise KeyError(f"'{question_class}' is not a coverage-matrix question_class")
    return row["source_module"]


def _target_entity_name(question_class: str) -> Optional[str]:
    row = _load_matrix_rows_by_class().get(question_class)
    if row is None:
        return None
    # A few rows annotate the entity with a parenthetical, e.g.
    # "DeepVisibilityEvent (not yet formalized as an ontology entity -- ...)"
    return row["target_entity"].split(" (")[0].strip()


def classify_empty_result(
    question_class: str,
    tool_error: Optional[str] = None,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    retention_days: Optional[int] = None,
) -> tuple[EmptyResultClassification, str]:
    """Classify a zero/empty tool result. Never call an empty result "clean"
    -- classify it as exactly one of the protocol's four buckets, with a
    human-readable reason citing the real, already-verified fact behind it.
    """
    entity_name = _target_entity_name(question_class)
    entities = _load_ontology_entities()
    entity = entities.get(entity_name) if entity_name else None

    if entity is not None and entity.get("in_scope") is False:
        return (
            EmptyResultClassification.NO_COVERAGE,
            f"{entity_name} is not confirmed licensed/enabled/populated on "
            f"this tenant: {entity.get('description', '')}",
        )

    if tool_error and _PERMISSION_ERROR_PATTERN.search(tool_error):
        return (
            EmptyResultClassification.SCOPE_OR_PERMISSION_ERROR,
            f"tool returned a permission/scope-shaped error: {tool_error}",
        )

    if window_start is not None and retention_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        if window_start < cutoff:
            return (
                EmptyResultClassification.OUTSIDE_RETENTION,
                f"window start {window_start.isoformat()} is before the "
                f"tenant's {retention_days}-day retention boundary",
            )

    label = entity_name.lower() if entity_name else "matching"
    return (
        EmptyResultClassification.NO_MATCHING_ACTIVITY,
        f"no matching {label} records for this query in the given scope/window",
    )


def _log_uncatalogued_enum(entity_name: str, enum_ref: str, raw_value: Any) -> None:
    INTERPRETATION_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "entity": entity_name,
        "enum_ref": enum_ref,
        "raw_value": raw_value,
    }
    with open(UNCATALOGUED_ENUM_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def decode_enum_value(entity_name: str, enum_ref: str, raw_value: Any) -> str:
    """Decode a raw enum value via the ontology's enum tables. On this
    tenant these are currently self-mapping (SentinelOne's Alerts GraphQL
    API returns human-readable strings, not numeric codes) -- decoding here
    is a validated-membership check, not a code translation, but the
    mechanism must still refuse to silently pass through a value that
    hasn't actually been observed and catalogued (no fabrication). Logs
    every miss so the ontology's enum tables can be grown from real
    observations, same pattern as the router's fallback candidate log.
    """
    entities = _load_ontology_entities()
    entity = entities.get(entity_name)
    enum_table = (entity.get("enums") or {}).get(enum_ref, {}) if entity else {}
    if raw_value in enum_table:
        return enum_table[raw_value]
    _log_uncatalogued_enum(entity_name, enum_ref, raw_value)
    return (
        f"{raw_value} (observed value, not yet catalogued in the "
        f"{entity_name}.{enum_ref} enum table)"
    )


def format_grounding_line(
    source_module: str,
    tenant: str,
    window: str,
    result_count: Optional[int] = None,
    empty_classification: Optional[EmptyResultClassification] = None,
    empty_reason: Optional[str] = None,
) -> str:
    """The mandatory grounding line every factual answer ends with."""
    if result_count is not None:
        results_part = str(result_count)
    elif empty_classification is not None:
        results_part = f"0 ({empty_classification.value})"
        if empty_reason:
            results_part += f" -- {empty_reason}"
    else:
        raise ValueError("must provide result_count or empty_classification")
    return (
        f"Source: {source_module} · Tenant: {tenant} · "
        f"Window: {window} · Results: {results_part}"
    )


def format_grounded_answer(
    body: str,
    source_module: str,
    tenant: str,
    window: str,
    result_count: Optional[int] = None,
    empty_classification: Optional[EmptyResultClassification] = None,
    empty_reason: Optional[str] = None,
) -> str:
    line = format_grounding_line(
        source_module, tenant, window, result_count, empty_classification, empty_reason
    )
    return f"{body.rstrip()}\n\n{line}"


def validate_query_or_refuse(decision: RouteDecision) -> RefusalGateResult:
    """The refusal gate. Called on a router decision before anything runs.

    No unvalidated queries: a route only proceeds unconditionally if it's
    hard-bound (gap-closing) or matched to a `status: stable` recipe. An
    experimental recipe requires analyst confirmation upstream of this
    call, not silent execution. Ambiguous intents are refused outright
    (ask first). Fallback is allowed but flagged, since the router already
    constrains it to ontology-narrowed real tools and logs it as a
    candidate recipe -- that's the brief's own "long tail feeds back into
    the matrix" design, not improvisation.
    """
    if decision.decision_type == "ambiguous":
        options = decision.disambiguation_options
        return RefusalGateResult(
            allowed=False,
            reason=(
                f"ambiguous between {options} (confidence "
                f"{decision.confidence}/{decision.second_best_confidence}) "
                "-- ask a disambiguating question before retrieving"
            ),
        )

    if decision.decision_type == "fallback":
        if decision.candidate_tools:
            return RefusalGateResult(
                allowed=True,
                reason=(
                    "no validated recipe covers this question; proceeding "
                    f"with ontology-narrowed candidate tools only "
                    f"{decision.candidate_tools} -- logged as a candidate "
                    "recipe for review, not treated as a confirmed pattern"
                ),
            )
        return RefusalGateResult(
            allowed=False,
            reason="no validated recipe and no candidate tools found for this question",
        )

    question_class = decision.question_class

    if question_class == SENTRY_INTERNAL_QUESTION_CLASS:
        return RefusalGateResult(
            allowed=True,
            reason=(
                "the one row where Sentry's own findings store IS the "
                "correct source -- not a SentinelOne question"
            ),
        )

    recipe = get_recipe_by_intent(question_class, include_experimental=True)

    if decision.decision_type == "hard_bound":
        if recipe is None or recipe.get("status") != "stable":
            raise RuntimeError(
                f"gap-closing question_class '{question_class}' is "
                "hard-bound but has no stable recipe -- build defect, not "
                "something to route around"
            )
        return RefusalGateResult(
            allowed=True,
            reason=(
                f"gap-closing intent, hard-bound to stable recipe "
                f"'{recipe['recipe_id']}' with no discretion"
            ),
        )

    # decision_type == "routed"
    if recipe is not None and recipe.get("status") == "stable":
        return RefusalGateResult(
            allowed=True,
            reason=f"routed to stable recipe '{recipe['recipe_id']}'",
        )

    if recipe is not None:
        return RefusalGateResult(
            allowed=False,
            reason=(
                f"recipe '{recipe['recipe_id']}' exists but is "
                "status=experimental -- requires analyst confirmation "
                "before running"
            ),
            closest_validated_path=recipe.get("expected_result_shape"),
        )

    matrix_row = _load_matrix_rows_by_class().get(question_class, {})
    return RefusalGateResult(
        allowed=False,
        reason=(
            f"no validated recipe covers '{question_class}' yet; the "
            "coverage matrix documents an unvalidated retrieval path"
        ),
        closest_validated_path=matrix_row.get("retrieval_path"),
    )
