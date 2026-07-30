"""Registers the validated SentinelOne recipe library for few-shot use.

Phase 2, Milestone 6. The recipes in `data/knowledge/sentinelone/recipes/`
were built and live-validated in Milestone 4. This module turns them into
compact few-shot examples the model can be shown alongside a routed
question -- "here is exactly how this class of question was answered before"
-- rather than re-deriving a tool call sequence from scratch. Only
`status: stable` recipes are included by default; `status: experimental`
recipes require the caller to opt in explicitly, mirroring the same gating
the router and the task execution protocol apply everywhere else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "recipes"


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_all_recipes() -> list[dict[str, Any]]:
    recipes = []
    for path in sorted(RECIPES_DIR.glob("*.yaml")):
        data = _read_yaml(path)
        if isinstance(data, dict) and "recipe_id" in data:
            recipes.append(data)
    return recipes


def load_recipes(include_experimental: bool = False) -> list[dict[str, Any]]:
    recipes = load_all_recipes()
    if include_experimental:
        return recipes
    return [r for r in recipes if r.get("status") == "stable"]


def get_recipe_by_intent(
    intent: str, include_experimental: bool = False
) -> Optional[dict[str, Any]]:
    for recipe in load_recipes(include_experimental=include_experimental):
        if recipe.get("intent") == intent:
            return recipe
    return None


def format_as_few_shot(recipe: dict[str, Any]) -> str:
    """One recipe as a compact few-shot block: intent, tool call sequence,
    expected result shape. Deliberately excludes validated_edge_cases and
    regression_fixture -- those are for the test harness, not the prompt."""
    calls = "\n".join(
        f"  {i + 1}. {tc['tool']}({tc.get('parameters', {})})"
        f"  # {tc.get('purpose', '')}"
        for i, tc in enumerate(recipe.get("tool_calls", []))
    )
    header = (
        f"Intent: {recipe['intent']} "
        f"(recipe: {recipe['recipe_id']}, status: {recipe['status']})"
    )
    return (
        f"{header}\n"
        f"Tool calls:\n{calls}\n"
        f"Expected result shape: {recipe.get('expected_result_shape', '')}"
    )


def get_few_shot_block(
    intents: Optional[list[str]] = None, include_experimental: bool = False
) -> str:
    """Few-shot block for one or more intents, or the whole stable library
    if `intents` is None. Joined with a blank line between recipes."""
    recipes = load_recipes(include_experimental=include_experimental)
    if intents is not None:
        recipes = [r for r in recipes if r.get("intent") in intents]
    return "\n\n".join(format_as_few_shot(r) for r in recipes)
