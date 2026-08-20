# Regression fixture: Investigator capability (Milestone 2)

Encodes Milestone 2's acceptance bar: *"Investigator reconstructs a chain
from a real threat, maps it to MITRE, lists the affected hosts, and every
step traces to a recipe call."*

## Case: entry alert has a storyline

- **expected_behavior**: composes `threat_detail` (to find `storylineId`)
  then `storyline_pivot` (the chain). Returns a chronological `timeline`,
  a distinct `affected_hosts` list, and an `assessment` with MITRE
  technique inference explicitly labeled as interpretation (SentinelOne's
  Alert entity has no structured MITRE field in this integration —
  confirmed Milestone 9's full tool-inventory scan).

## Case: entry alert has no storyline

- **expected_behavior**: `storyline_pivot` is never called. Returns
  `kind="answered"` (a single alert with no broader chain is not a
  failure) with an assessment stating plainly that there is no chain to
  map.

## Pass criteria (`tests/unit/test_investigator_capability.py`)

1. Composes only through `services.sentinelone_recipe_executor.execute()`.
2. `storyline_pivot` is only invoked when `threat_detail`'s raw_data
   carries a real `storyline_id`.
3. The timeline is built from `storyline_pivot`'s raw chain data, sorted
   chronologically, never fabricated.
4. Affected hosts are the distinct asset names actually present in the
   chain, never guessed.
5. An LLM/synthesis failure is caught and returned as `execution_error`,
   never raised uncaught.
