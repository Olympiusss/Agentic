# Router index and route log (Milestone 6, generated -- not committed)

This directory holds two files, neither committed to git (see `.gitignore`):

- `coverage_matrix_index.json` -- every coverage-matrix example question,
  embedded with the local model in `services/sentinelone_embeddings.py`.
  Deterministically regenerated from
  `data/knowledge/sentinelone/coverage_matrix/sentinelone_coverage_matrix.yaml`
  by `scripts/build_sentinelone_router_index.py`. Not committed because it's
  a large (~800KB), engine-specific float blob -- a build artifact, not
  hand-reviewable knowledge content like every other file in this phase.
- `route_log.jsonl` -- one JSON line per routing decision made by
  `services/sentinelone_router_service.route()`: the question, the matched
  intent, the confidence, the matched example, the chosen recipe/tool, the
  source, and whether it was hard-bound, routed, ambiguous, or fallback.
  Grows with real usage; per the build brief, this log plus the coverage
  matrix is the Milestone 8 regression set.

**Before using the router for the first time** (or after changing the
coverage matrix), run:

```bash
python scripts/build_sentinelone_router_index.py
```

To verify the router's Milestone 6 acceptance criteria (gap-closing set
resolves correctly, ambiguity is caught, fallback is constrained, every
route is logged), run:

```bash
python scripts/validate_sentinelone_router.py
```
