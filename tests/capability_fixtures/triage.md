# Regression fixture: Triage capability (Milestone 1)

Encodes Milestone 1's acceptance bar (`Sentry_AgenticSOC_Capabilities_Brief_for_Antigravity.md`):
*"Triage returns a grounded verdict with evidence and confidence on real
threats, and never asserts a judgement without the evidence behind it."*

## Case: happy path, alert has a storyline

- **input**: a real alert_id
- **expected_behavior**: `capabilities.triage.run_triage(alert_id)` calls
  `threat_detail` (grounded alert detail), then, since the alert carries a
  `storylineId`, also calls `storyline_pivot` (blast radius), then
  synthesizes via `llm_gateway.submit_triage`. Returns `kind="answered"`
  with `evidence` (a list of the retrieved, already-grounded recipe
  answers) and `assessment` (verdict/severity/blast-radius/confidence/
  reasoning, clearly separated from the evidence).

## Case: alert has no storyline

- **expected_behavior**: `storyline_pivot` is not called (or is called and
  returns nothing) -- the assessment states plainly that blast radius
  could not be estimated, never a guessed number. `kind` is still
  `"answered"` -- a missing storyline is not a failure.

## Case: alert not found

- **expected_behavior**: `threat_detail` itself returns its own empty/
  grounded "no alert found" answer (existing behavior, unchanged) --
  Triage still synthesizes over that, or, if no evidence at all comes
  back, refuses (`kind="execution_error"`) rather than asking Claude to
  invent a verdict from nothing.

## Case: alert already has a human analyst verdict on record

- **expected_behavior**: `threat_detail`'s answer already includes
  "Analyst activity: ... changed the analyst verdict ..." (Milestone 9
  enrichment). The synthesis instructions require treating this as the
  strongest signal and saying so explicitly, not silently overriding it
  with a fresh, unexplained verdict.

## Pass criteria (for `tests/unit/test_triage_capability.py`)

1. Composes only through `services.sentinelone_recipe_executor.execute()`
   -- never a raw MCP tool call, never `services.mcp_client` directly.
2. `storyline_pivot` is only invoked when `threat_detail`'s `raw_data`
   carries a real `storyline_id` -- proves the conditional-chaining logic,
   not just a static two-step plan.
3. The synthesis prompt sent to `llm_gateway.submit_triage` contains the
   retrieved evidence text verbatim -- proves synthesis reasons over real
   retrieved facts, not a fabricated summary.
4. A failure from `threat_detail` (execution_error / needs_clarification)
   short-circuits before any LLM call is made.
5. An LLM call failure/timeout is caught and returned as
   `kind="execution_error"`, never raised uncaught.
