# Regression fixture: Threat Hunter capability (Milestone 3)

Encodes Milestone 3's acceptance bar: *"Hunter runs the stable templates on
the tenant, returns hits per host with MITRE tags, and stays within the
guardrails."*

Real constraint found while building: **all 11 dv_cookbook templates are
currently `status: experimental`**, none `stable`. The brief's own
guardrail — *"never run an experimental template without confirmation"* —
is enforced literally: an unconfirmed call refuses to execute anything.

## Case: unconfirmed call

- **expected_behavior**: `run_threat_hunter(confirmed=False)` (the
  default) returns `kind="needs_confirmation"` naming every experimental
  template it would have run. No `powerquery` call is made.

## Case: confirmed call

- **expected_behavior**: `run_threat_hunter(template_ids=[...],
  confirmed=True)` runs each named template's query via `powerquery` over
  the stated window, returns one `HuntHit` per template with its
  `match_count` (capped at the template's own `result_cap`), `mitre` tags,
  and `false_positives_observed` notes verbatim from the cookbook.

## Case: a single template call fails

- **expected_behavior**: that template's `HuntHit.error` is set and
  `match_count` is `None` -- one bad template does not fail the whole hunt
  run for the others.

## Pass criteria (`tests/unit/test_threat_hunter_capability.py`)

1. Unconfirmed calls never invoke `powerquery`.
2. Confirmed calls invoke `powerquery` once per requested template.
3. `match_count` never exceeds the template's own `result_cap`.
4. `mitre` and `false_positives_observed` are passed through verbatim from
   the template YAML, never fabricated.
