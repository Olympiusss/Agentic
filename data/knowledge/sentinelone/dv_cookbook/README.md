# Deep Visibility / PowerQuery cookbook (Milestone 5)

Built from the detected event schema in `../environment_map.yaml`, validated against `data/schemas/dv_template.schema.json`.

Contents: a field dictionary (event types mapped to valid fields/operators, confirmed by real queries, not guessed), one MITRE-tagged template per core hunt pattern (living-off-the-land, credential access, persistence, process injection, lateral movement, exfiltration), the storyline pivot as a reusable recipe, and mandatory defaults (explicit window, result cap, smallest-query-first).

Critical constraint carried over from Phase 1 verification and `mcp_tools.md`: the `powerquery` tool's own instructions say the agent should get PowerQuery strings from `purple_ai()` rather than hand-composing them, and a malformed/legacy field name can close the whole MCP connection rather than just error. Every template here must be validated against the live tenant before being marked `stable`; `experimental` templates require analyst confirmation before execution.
