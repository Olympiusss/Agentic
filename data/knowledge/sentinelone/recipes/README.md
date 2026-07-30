# Retrieval recipes (Milestone 4)

One parametrised recipe per coverage-matrix row, in priority order starting with the gap-closing set. Validated against `data/schemas/recipe.schema.json`.

Each recipe: intent, inputs, the exact tool call sequence (tool name + parameters — see `../mcp_tools.md` for the real, live-verified schemas), and expected result shape. Every recipe is validated against the live tenant before being tagged; the true result and edge cases (empty, paginated, throttled, out of retention, permission error) are captured, not assumed. Only `status: stable` recipes run without analyst confirmation — `status: experimental` requires sign-off first.

The threat/alert-count recipe in particular must route to `search_alerts` with `first=1` and read `totalCount` (the tool's own documented pattern — see `mcp_tools.md`), and must pass the regression fixture at `tests/fixtures/threat_count_source.md`.
