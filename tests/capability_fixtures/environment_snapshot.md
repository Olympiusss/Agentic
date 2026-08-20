# Regression fixture: capability framework proof-of-mechanism (Milestone 0)

Encodes Milestone 0's own acceptance bar (`Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md`,
"Milestone 0. Capability framework and registry"): *"The runner executes a
trivial capability end to end, composes only through the recipe layer,
refuses a plan that references a raw tool, and produces a grounded
output."* `environment_snapshot` is that trivial capability -- not one of
the six specialist roles, purely a mechanism proof.

## Case: happy path

- **capability_id**: `environment_snapshot`
- **plan**: `endpoint_count`, `group_count`, `tenant_structure` (all
  no-input, already-stable recipes)
- **expected_behavior**: `capabilities.runner.run_capability("environment_snapshot", {})`
  returns `kind="answered"`, with one `StepResult` per plan step, each
  carrying the recipe's own already-grounded `answer` string (ending in
  `Source: ... · Client: ...`). The capability's own `output` is those
  three answers concatenated, in plan order.

## Case: composition-rule enforcement

- A plan step with `"type": "tool"` (a raw MCP tool reference) must be
  refused (`kind="refused"`) before any recipe executes -- never silently
  ignored, never partially executed.
- A plan step referencing an unknown/non-existent recipe intent must also
  be refused, with a reason naming the missing recipe.

## Pass criteria (for `tests/unit/test_capability_runner.py`)

1. `run_capability("environment_snapshot", {})` returns `kind == "answered"`.
2. Every `StepResult.answer` contains the grounding anchor (`Source:` and
   `Client:`) -- the capability framework does not strip or invent
   grounding, it composes recipes that already carry it.
3. A synthetic spec containing a `{"type": "tool", "ref": "list_alerts"}`
   step is refused (`kind == "refused"`) with a reason mentioning "raw
   tool" -- proves the composition-only rule is enforced before
   execution, not just documented in the schema.
4. A synthetic spec referencing a non-existent recipe intent is refused
   with a reason naming the missing recipe.
5. No step in any test ever calls `services.mcp_client` or any raw tool
   directly -- only `services.sentinelone_recipe_executor.execute()`, the
   same entry point live chat already uses.
