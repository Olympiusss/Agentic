# Coverage matrix (Milestone 3)

The question-to-retrieval spine — both the build backlog and the Milestone 8 test set. Validated against `data/schemas/coverage_matrix.schema.json`.

Columns: question class, example question, target entity, source module, retrieval path, MITRE technique (if applicable), expected result shape, priority, status.

Seeded from the modules actually present in this tenant (per `mcp_tools.md` and `environment_map.yaml`) and the Deep Visibility hunt patterns. The gap-closing set is flagged first: alert/threat count (bound to `search_alerts`, not an assumed "Threats" tool — see `../mcp_tools.md`'s corrections section), host lookup, storyline pivot, agent health, CVE traversal. Includes a hook for analyst-elicited questions beyond the seeded set.
