"""Capability runner (Phase 3, Milestone 0 --
Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md).

Executes a capability by composing already-validated SentinelOne recipes
and stable Deep Visibility templates -- it never calls a raw MCP tool
directly. This module is the enforcement point for the brief's central
rule ("a capability composes recipes, it does not invent retrieval"): a
plan step that isn't a known, validated recipe/template, or that names a
raw tool, is refused before anything executes.

Real synthesis (Claude reasoning over the collected, grounded results) is
each capability's own job starting with Triage (Milestone 1) -- this
runner's job stops at composing recipe calls and collecting their already-
grounded answers, matching the brief's own separation between the
framework (Milestone 0) and the specialist capabilities built on it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_DIR = Path(__file__).resolve().parent
SPECS_DIR = CAPABILITIES_DIR / "specs"
REGISTRY_PATH = CAPABILITIES_DIR / "registry.yaml"
DV_COOKBOOK_DIR = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "dv_cookbook"


@dataclass
class StepResult:
    name: str
    ref: str
    ref_type: str
    outcome_kind: str  # mirrors RecipeOutcome.kind: "answered" | "needs_clarification" | "execution_error"
    answer: Optional[str] = None
    error: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None


@dataclass
class CapabilityOutcome:
    kind: str  # "answered" | "needs_clarification" | "execution_error" | "refused"
    steps: list[StepResult] = field(default_factory=list)
    output: Optional[str] = None
    clarifying_question: Optional[str] = None
    error: Optional[str] = None


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_registry() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    return _read_yaml(REGISTRY_PATH).get("capabilities", [])


def load_spec(capability_id: str) -> Optional[dict[str, Any]]:
    path = SPECS_DIR / f"{capability_id}.yaml"
    if not path.exists():
        return None
    return _read_yaml(path)


def _validate_plan_composition(plan: list[dict[str, Any]]) -> Optional[str]:
    """Fail-closed check: every plan step must reference a known, stable
    recipe or dv_hunt template -- never a raw tool, never an unrecognized
    reference. Returns a refusal reason, or None if the plan is clean."""
    from services.sentinelone_recipe_library import get_recipe_by_intent

    for step in plan:
        ref_type = step.get("type")
        ref = step.get("ref")

        if ref_type == "recipe":
            recipe = get_recipe_by_intent(ref, include_experimental=False)
            if recipe is None:
                return (
                    f"plan references '{ref}' as a recipe, but no stable recipe with that "
                    "intent exists in data/knowledge/sentinelone/recipes/ -- author and "
                    "validate it as a recipe first (brief section 5)"
                )
        elif ref_type == "template":
            if not (DV_COOKBOOK_DIR / f"{ref}.yaml").exists():
                return f"plan references '{ref}' as a dv_hunt template, but no such template exists"
        elif ref_type == "tool":
            return (
                f"plan references a raw tool '{ref}' directly -- capabilities may only "
                "compose recipes/templates through the existing routing and recipe layer, "
                "never call a raw tool (Capabilities Brief section 3/5)"
            )
        else:
            return f"plan step has unrecognized type '{ref_type}' -- must be 'recipe' or 'template'"

    return None


async def run_capability(capability_id: str, inputs: Optional[dict[str, Any]] = None) -> CapabilityOutcome:
    """Execute one capability end to end: load its spec, enforce the
    composition-only rule, run each plan step through the existing
    production recipe executor (services.sentinelone_recipe_executor --
    the same entry point live chat uses, never a raw MCP tool call), and
    collect the already-grounded results. Never raises -- mirrors the
    recipe executor's own never-raise contract."""
    inputs = inputs or {}
    spec = load_spec(capability_id)
    if spec is None:
        return CapabilityOutcome(kind="execution_error", error=f"no capability spec found for '{capability_id}'")

    plan = spec.get("plan", [])
    violation = _validate_plan_composition(plan)
    if violation:
        logger.warning("Capability '%s' refused: %s", capability_id, violation)
        return CapabilityOutcome(kind="refused", error=violation)

    from services import sentinelone_recipe_executor as executor

    steps: list[StepResult] = []
    for step in plan:
        ref_type = step.get("type")
        ref = step.get("ref")
        name = step.get("name", ref)

        if ref_type != "recipe":
            # Template (DV hunt) execution is wired when the Hunter
            # capability (Milestone 3) needs it -- Milestone 0's own
            # trivial capability only composes no-input count recipes.
            steps.append(StepResult(name=name, ref=ref, ref_type=ref_type, outcome_kind="execution_error", error="template step execution not yet wired (Milestone 3)"))
            continue

        try:
            question_template = step.get("question_template")
            question = question_template.format(**inputs) if question_template else name
            outcome = await executor.execute(ref, question)
        except Exception as e:  # noqa: BLE001
            return CapabilityOutcome(
                kind="execution_error",
                steps=steps,
                error=f"step '{ref}' raised: {e}",
            )

        step_result = StepResult(
            name=name,
            ref=ref,
            ref_type=ref_type,
            outcome_kind=outcome.kind,
            answer=outcome.answer,
            error=outcome.error,
            raw_data=outcome.raw_data,
        )
        steps.append(step_result)

        if outcome.kind == "execution_error":
            return CapabilityOutcome(
                kind="execution_error",
                steps=steps,
                error=f"step '{ref}' failed: {outcome.error}",
            )
        if outcome.kind == "needs_clarification":
            return CapabilityOutcome(
                kind="needs_clarification",
                steps=steps,
                clarifying_question=outcome.clarifying_question,
            )

    # Milestone 0 has no synthesis step -- the output is the composed,
    # already-grounded recipe answers concatenated in plan order. Real
    # synthesis (Claude reasoning over these results) is each specialist
    # capability's own job starting with Triage.
    answers = [s.answer for s in steps if s.answer]
    output = "\n\n".join(answers) if answers else None
    return CapabilityOutcome(kind="answered", steps=steps, output=output)
