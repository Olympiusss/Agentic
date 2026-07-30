# Coverage matrix (Milestone 3 — populated; Milestone 8 test set, executed)

The question-to-retrieval spine — both the build backlog and the Milestone 8 test set. 12 rows in `sentinelone_coverage_matrix.yaml`, all validated against `data/schemas/coverage_matrix.schema.json`. Built from Milestones 0-2's already-verified facts — no new live tenant queries were needed for this milestone.

**Milestone 8 ran this matrix for real against the live tenant and published the results: `accuracy_report.md`, 12/12 rows passing (100%), gap-closing 5/5 (100%), the Milestone 0 regression fixture passing all 5 literal criteria.** Reproducible via `python tests/sentinelone_coverage_harness.py` or `pytest tests/test_sentinelone_coverage_matrix.py`.

Columns: question class, example questions, target entity, source module, retrieval path, MITRE technique (if applicable), expected result shape, priority, status, forbidden source.

**The gap-closing set** (`priority: gap_closing`) is hard-bound per the brief, no router discretion once Milestone 6 wires it up: `threat_count` (bound to `search_alerts`, not an assumed "Threats" tool — see `../mcp_tools.md`'s corrections section), `host_lookup`, `storyline_pivot`, `agent_health`, `cve_traversal`. All 5, plus `threat_detail` and `vulnerability_general`, carry `status: stable` (corrected Milestone 7 — their bound recipes have been `stable` since Milestone 4's live validation; this row-level field just hadn't been bumped to match).

**Other rows**: `threat_detail`, `vulnerability_general` (both `priority: high`), `dv_hunt` (medium — routes through `purple_ai()` first, per that tool's own documented instructions, not hand-composed PowerQuery), and three intentionally-unavailable rows recorded rather than omitted — `identity_security` (unlicensed), `activity_audit` (no tool exists in this MCP server), `cloud_misconfiguration` (not confirmed populated) — plus `sentry_internal`, the one row where Sentry's own findings store *is* the correct source (the control case every other row's `forbidden_source` points away from).

**Adding an analyst-elicited question** (the hook the brief calls for): add a new row following the same schema, and set `elicited_by` to who/when it was added — this distinguishes it from the tenant-module-seeded rows above, which leave `elicited_by` unset. No new tooling is needed; the schema already supports this.

Each row's `status` is honest about what's actually been run: `stable` means the bound recipe is live-validated and usable without analyst confirmation (per `data/schemas/coverage_matrix.schema.json`); `validated` and `recipe_drafted` are earlier, superseded states; `not_started` covers both "not yet tried" and "no tool available." Milestone 4 turns each row into an actually-validated, parametrised recipe; Milestone 7 wires `status: stable` into the actual refusal gate (`services/sentinelone_grounding_service.py`).
