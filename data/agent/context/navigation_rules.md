# Navigation rules (distilled)

How a question becomes a tool call. This is not model discretion -- it is a
fixed procedure implemented in `services/sentinelone_router_service.py`. Do
not re-derive routing by reasoning over the full 33-tool surface; call the
router.

1. **The server is fixed.** One `sentinelone` MCP server, bound to this
   session. Never chosen from the question text.
2. **Intent is resolved by embedding match, not free classification.** The
   router embeds the incoming question with a local model and compares it
   against pre-embedded example questions from every row of
   `data/knowledge/sentinelone/coverage_matrix/sentinelone_coverage_matrix.yaml`.
   The nearest row's `question_class` is the candidate intent.
3. **Confidence threshold.** Below `ROUTER_CONFIDENCE_THRESHOLD` (0.55,
   defined in `sentinelone_router_service.py`), nothing matched well enough
   -- go to the constrained fallback (step 6).
4. **Ambiguity tie-break.** If the top two candidate rows' scores are within
   `ROUTER_AMBIGUITY_GAP` (0.05) of each other, the intent is ambiguous. Ask
   one disambiguating question naming both candidate classes, or let a light
   model pass choose only between those two -- never silently pick one.
5. **The gap-closing set is hard-bound, no exceptions.** Once intent
   resolves uniquely to one of `threat_count`, `host_lookup`,
   `storyline_pivot`, `agent_health`, or `cve_traversal` (the rows with
   `priority: gap_closing`), the router returns that row's bound recipe from
   `data/knowledge/sentinelone/recipes/` and nothing else. No model
   discretion, no fallback, no reasoning about whether a different tool might
   fit better.
6. **Constrained fallback -- never the full tool surface.** When nothing
   clears the threshold, the router narrows candidates through the ontology:
   it retrieves the nearest ontology-entity chunks from
   `services/sentinelone_retrieval_store.py` and returns only the tool
   bindings of those entities. The model reasons over that short list, never
   all 33 tools. The call is logged as a candidate recipe for review -- it
   feeds back into the coverage matrix instead of being re-guessed next time.
7. **Non-gap-closing matched rows** (e.g. `threat_detail`,
   `vulnerability_general`) resolve to that row's `retrieval_path` and
   `source_module` directly; use the matching recipe in `recipes/` if one
   exists and is `status: stable`, otherwise treat it like the constrained
   fallback -- state what's being tried and why.
8. **Every route is logged**, unconditionally: the question, the matched
   intent, the confidence, the matched example, the chosen recipe/tool, the
   source, and whether it was hard-bound, routed, ambiguous, or fallback.
   This log plus the coverage matrix is the Milestone 8 regression set.
9. **Tool descriptions in `data/agent/tools/` are consulted only on the
   fallback path** (step 6) -- they exist to help the model choose correctly
   among a narrowed set, especially to avoid confusing Alerts, Deep
   Visibility, and Sentry's internal findings. They are never loaded as
   context on the primary, hard-bound, or matched-row paths.
