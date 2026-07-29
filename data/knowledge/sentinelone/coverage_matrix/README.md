# Coverage matrix (Milestone 3 — populated, draft pending review)

The question-to-retrieval spine — both the build backlog and the Milestone 8 test set. 12 rows in `sentinelone_coverage_matrix.yaml`, all validated against `data/schemas/coverage_matrix.schema.json`. Built from Milestones 0-2's already-verified facts — no new live tenant queries were needed for this milestone.

Columns: question class, example questions, target entity, source module, retrieval path, MITRE technique (if applicable), expected result shape, priority, status, forbidden source.

**The gap-closing set** (`priority: gap_closing`) is hard-bound per the brief, no router discretion once Milestone 6 wires it up: `threat_count` (bound to `search_alerts`, not an assumed "Threats" tool — see `../mcp_tools.md`'s corrections section; the only gap-closing row already live-`validated`, not just drafted), `host_lookup`, `storyline_pivot`, `agent_health`, `cve_traversal`.

**Other rows**: `threat_detail`, `vulnerability_general` (both `priority: high`), `dv_hunt` (medium — routes through `purple_ai()` first, per that tool's own documented instructions, not hand-composed PowerQuery), and three intentionally-unavailable rows recorded rather than omitted — `identity_security` (unlicensed), `activity_audit` (no tool exists in this MCP server), `cloud_misconfiguration` (not confirmed populated) — plus `sentry_internal`, the one row where Sentry's own findings store *is* the correct source (the control case every other row's `forbidden_source` points away from).

**Adding an analyst-elicited question** (the hook the brief calls for): add a new row following the same schema, and set `elicited_by` to who/when it was added — this distinguishes it from the tenant-module-seeded rows above, which leave `elicited_by` unset. No new tooling is needed; the schema already supports this.

Each row's `status` is honest about what's actually been run: `validated` means the retrieval path was live-tested in an earlier milestone; `recipe_drafted` means it's described here but not yet exercised; `not_started` covers both "not yet tried" and "no tool available." Milestone 4 turns each row into an actually-validated, parametrised recipe.
