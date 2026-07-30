# Retrieval recipes (Milestone 4 — populated)

7 recipes, one file per recipe, built and live-validated by `scripts/validate_sentinelone_recipes.py`, all `status: stable`, all validated against `data/schemas/recipe.schema.json`:

- **Gap-closing set** (all 5): `threat_count_by_window`, `host_lookup`, `storyline_pivot`, `agent_health`, `cve_traversal`.
- **Also built** (low-risk, `priority: high` rows reusing already-confirmed tool calls): `threat_detail`, `vulnerability_general`.

Every recipe was executed against the live tenant this milestone, with real parameter values pulled live (a real `storylineId`, hostname substring, CVE ID, alert ID) rather than placeholders — `status: stable` is only ever set from an actual successful live run, never a dry run. Real edge cases captured:
- **Empty result** (genuinely tested, not simulated): `host_lookup` and `cve_traversal` were each run against a deliberately nonexistent value and returned real empty lists, not errors.
- **Paginated**: `vulnerability_general` tried three times (different filters, `first=2` then `first=1`) to force a real second page — every attempt found `hasNextPage: false`. This tenant genuinely has only 1 total vulnerability record right now, so pagination is honestly recorded as untestable here, not faked.
- **Throttled / permission error / out of retention**: deliberately **not** forced this milestone — would require degrading credentials or hammering rate limits against a real tenant, not worth the risk for a documentation exercise. Recorded as untested in each recipe, not fabricated.

**Deferred, not silently dropped** (see the coverage matrix for the reasoning already established in Milestone 3): `dv_hunt` (belongs after Milestone 5's DV cookbook exists, since `powerquery`'s own guidance is to route through `purple_ai()` first), `identity_security`/`activity_audit`/`cloud_misconfiguration` (no tool exists, or not confirmed populated — nothing to validate as a recipe), `sentry_internal` (a different MCP server, `sentry-findings`, not exercised in this SentinelOne-focused work).

**Regression fixture cross-check** (`tests/fixtures/threat_count_source.md`): of its 5 pass criteria, **#1** (routes to `search_alerts`, never a Sentry-internal tool) and **#5** (gap-closing, hard-bound in the coverage matrix) are fully satisfied now — live-validated, stable. Criteria **#2-4** (naming the source in the final answer, the grounding line, zero-result classification) are about the *answer format*, which belongs to Milestone 7's grounding/interpretation layer and the Milestone 6 router — neither exists yet, so those criteria can't be truly exercised end-to-end until then. This milestone's job was retrieval correctness, which is done; the fixture's full pass is a Milestone 8 harness concern.
