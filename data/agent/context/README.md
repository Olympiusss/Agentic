# Agent context (Milestone 6)

Distilled, always-on system-prompt fragments -- the compact subset of the
ontology, coverage matrix, and task execution protocol the agent needs on
*every* turn. Kept deliberately short (each file targets roughly 400-600
words, well under 1,000 tokens) because this loads into every conversation's
context budget, unlike the full protocol in `data/agent/protocol/` or the
retrieval store in `data/knowledge/sentinelone/retrieval_store/`, which are
consulted on demand.

| File | Purpose | Distilled from |
|---|---|---|
| `ontology_core.md` | What exists in the tenant: entities, sources, in/out of scope, tenant hierarchy | `data/knowledge/sentinelone/ontology/sentinelone_ontology.yaml`, `environment_map.yaml` |
| `navigation_rules.md` | How a question becomes a tool call: the router, the hard-bound gap-closing set, the constrained fallback | `Sentry_AgenticSOC_Build_Brief_for_Claude.md` §Milestone 6, `data/agent/protocol/task_execution_protocol.md` §3 |
| `grounding_rules.md` | The seven-principle grounding contract and the answer-format line, condensed | `data/agent/protocol/task_execution_protocol.md` §1, §5, §6 |

Nothing here is new information -- every fact traces back to a milestone 0-5
artifact or the brief itself. If a fact changes upstream (e.g. the ontology is
re-reviewed, a new gap-closing recipe ships), update these files to match;
do not let them drift into their own source of truth.
