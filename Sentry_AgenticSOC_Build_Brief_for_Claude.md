# Sentry Agentic SOC: Implementation Brief for Antigravity

You are Antigravity, the build agent implementing the Sentry agentic SOC. This brief translates the design decisions into an exact, ordered implementation plan you will act on. Read it fully before you start. Confirm the existing repository and stack before creating anything, and adapt to what is already there rather than assuming.

Scope for this phase is deliberately narrow. Build environmental understanding first, on one established tenant. Agent capabilities come after and are out of scope here.

---

## 1. Context: the system today

- Phase 1 is complete. There is a working architecture with a live pipeline from one established SentinelOne tenant into Sentry.
- Reasoning is Claude through the Anthropic API. SentinelOne is reached through a purple-mcp MCP server that exposes SentinelOne as callable tools. Confirm the exact stack and the MCP tool inventory in the repo before building. The plan of record also references Docker with Compose, Redis, PostgreSQL, FastAPI, a React interface, and Python. Treat that as the expected stack to confirm, not to assume.
- The agent already connects and returns results. It is not yet accurate, and that is what this phase fixes.

---

## 2. The problem concern

In a retrieval test, the agent was asked how many threats existed in the environment. It answered "0 findings" from Sentry's own internal findings store instead of the SentinelOne threat data, and stated it with unearned confidence, padding the answer with generic caveats.

The failure is not a bug in one tool. It is the absence of two things:

1. A grounded model of the environment. The agent has no navigable understanding of what exists in the tenant, how it is structured, or which source answers which question.
2. A retrieval and grounding discipline. The agent does not route a question to the correct source, does not state its source and scope, and reads an empty result as a clean environment.

Left unfixed, this produces confident wrong answers, wrong-source retrieval, hallucinated field names, and "empty means clean" errors. For a SOC, that is worse than no answer.

---

## 3. The solution

The core principle is **retrieve, do not recall**. The data lives in SentinelOne and is pulled live on every question. The agent holds the map, not the data. This keeps answers current and is the main defence against hallucination.

The world model has three layers:

- **Semantic layer, the ontology.** The entities in the tenant, their real attributes, their relationships, the enums in use, and their lifecycle states. Built from what the tenant actually returns, not from a generic decomposition.
- **Retrieval layer.** For each class of question, the one canonical path to the answer: which tool, which parameters, which query. This is the coverage matrix, and it doubles as the test set. How the agent resolves a question to the right row at run time is the routing method, specified in Milestone 6.
- **Interpretation layer.** How to read and reconcile results, when an empty result is genuinely clean versus a scope or retention artifact, and the rule that every answer names its source, the tenant, the time window, and the result count.

The knowledge is placed across five stores, each holding the part it is suited to: the agent system prompt or context, the MCP tool schema descriptions, a retrieval-augmented store, a validated recipe library, and an environment memory cache.

Deep Visibility gets dedicated treatment because it is the richest source and the one most prone to malformed queries and misread emptiness: a field dictionary, MITRE-tagged query templates gated by status, the storyline pivot, and hard guardrails on window and result size.

The coverage matrix is the spine of the whole phase. It is the build backlog and the test set at once.

Two companion artifacts already exist and you will wire them in:

- `Sentry_Agent_Task_Execution.md`, the operating contract the agent follows on every retrieval.
- `Sentry_Agent_Environmental_Understanding_Task.md`, the read-only discovery task the agent runs against the tenant to produce its environment map.

---

## 4. Scope and sequence

- **One established tenant only.** Do not build multi-tenant orchestration, do not add tenants, and do not gate acceptance on multiple tenants. Everything is scoped to this one environment.
- **Order.** Environmental understanding through ontology formalisation comes first. Agent capabilities come after, in a later phase.
- **Read-only.** All discovery and testing observe the environment. Nothing mitigates, isolates, tickets, or changes state. Response actions belong to a later objective.

---

## 5. Constraints and guardrails (non-negotiable)

- Every environmental fact comes from a live tool call. Never write a value you did not retrieve. Never invent a field name, ID, hostname, hash, CVE, or count.
- Detect and confirm the Deep Visibility query surface (standard query language, PowerQuery, or both) and the retention window from the tenant. Do not hardcode them.
- Enumerate the purple-mcp tool inventory from the server. Do not assume tool names; bind to what is actually exposed.
- Every Deep Visibility query is windowed and result-capped. Ask before running anything broad or expensive.
- Keep all knowledge artifacts model-agnostic, in YAML and markdown, so a future self-hosted reasoning model can reuse them without change. Only the tool bindings and the prompt wrapper should be engine-specific.
- Preserve tenant isolation and read-only operation throughout.

---

## 6. Repository and artifact layout

Create this structure under the knowledge root, adapting names to the existing repo conventions:

```
/knowledge
  /ontology            sentinelone_ontology.yaml, enum tables
  /coverage_matrix     the question-to-retrieval spine
  /recipes             validated, parametrised retrieval recipes
  /dv_cookbook         field dictionary, hunt templates, storyline pivot
  environment_map.yaml the grounded map produced by discovery
/agent
  /context             the distilled system prompt and navigation rules
  /tools               enriched MCP tool schema descriptions
  /protocol            the task execution protocol (imported)
/discovery             the read-only environment discovery runner
/tests                 the harness, the coverage-matrix run, fixtures
/schemas               ontology, matrix, recipe, and template schemas
```

---

## 7. Step by step implementation plan

Work milestone by milestone. Do not start a milestone until its predecessor's acceptance passes. Commit in small, verifiable steps.

### Milestone 0. Repository, schemas, and the regression fixture

- [ ] Confirm the existing Sentry repo and stack, and enumerate the purple-mcp tool inventory and the SentinelOne surfaces available for this tenant. Write the tool list to `/schemas/mcp_tools.md`.
- [ ] Create the repository layout in section 6.
- [ ] Define the schemas: ontology entity schema, coverage matrix columns, recipe metadata, and Deep Visibility template metadata. Put them in `/schemas`.
- [ ] Import the two companion artifacts into `/agent/protocol` and `/discovery`.
- [ ] Encode the regression fixture: the question "how many threats" must resolve to the SentinelOne threat source, never to Sentry findings, and must return a grounded answer with source, tenant, window, and count. Store it in `/tests/fixtures/threat_count_source.md`.

**Acceptance.** The repo builds, the schemas validate, the tool inventory is documented, and the fixture is committed.

### Milestone 1. Environment discovery runner

- [ ] Implement a read-only runner in `/discovery` that drives the agent through `Sentry_Agent_Environmental_Understanding_Task.md` against the tenant, with every query windowed and capped.
- [ ] Walk the environment top down: hierarchy, endpoints, policies, threats and storylines, alerts and incidents, vulnerabilities and applications, the optional modules, the Deep Visibility profile, the enums, and the tool bindings.
- [ ] Emit `/knowledge/environment_map.yaml` recording, for each area, what exists, the counts, the real attribute sets, the source names, the licensed or empty state, and the tool used per item.

**Acceptance.** The environment map is generated from the live tenant, the threat source is confirmed and named, the Deep Visibility surface and retention are detected, and no field is present that was not retrieved.

### Milestone 2. Ontology formalisation

- [ ] Generate `/knowledge/ontology/sentinelone_ontology.yaml` from the environment map: entities, attributes with population noted, relationships as edges, decoded enums, lifecycle states, and per-entity tool bindings.
- [ ] Mark anything from the generic decomposition that is not present in this tenant as out of scope for now.
- [ ] Insert a human review checkpoint for analyst sign-off before freezing version 1.

**Acceptance.** The ontology is derived only from the environment map, is reviewed, and is versioned.

### Milestone 3. Coverage matrix

- [ ] Generate `/knowledge/coverage_matrix` seeded from the modules present in this tenant and the Deep Visibility hunt patterns. Columns: question class, example, target entity, source module, retrieval path, MITRE technique, expected result shape, priority, status.
- [ ] Flag the gap-closing set first: threat count, host lookup, storyline pivot, agent health, and CVE traversal.
- [ ] Provide a hook to add analyst-elicited questions.

**Acceptance.** The matrix is seeded, prioritised, and the gap-closing set is flagged.

### Milestone 4. Retrieval recipes

- [ ] For each matrix row in priority order, starting with the gap-closing set, author a parametrised recipe: intent, inputs, tool call sequence, and expected result shape, in `/knowledge/recipes`.
- [ ] Validate each recipe against the live tenant and capture the true result and its edge cases: empty, paginated, throttled, out of retention, and permission error.
- [ ] Tag each recipe stable or experimental. Only stable runs without analyst confirmation.

**Acceptance.** The gap-closing set is fully validated and stable, and the threat-count recipe routes to the SentinelOne threat source and passes the fixture.

### Milestone 5. Deep Visibility cookbook

- [ ] Build the field dictionary in `/knowledge/dv_cookbook` from the detected event schema: event types mapped to their valid fields and operators.
- [ ] Author one MITRE-tagged template per core hunt pattern: living-off-the-land, credential access, persistence, process injection, lateral movement, and exfiltration.
- [ ] Validate each template on the tenant, record false positives, and gate status stable or experimental.
- [ ] Implement the storyline pivot as a reusable recipe, and set the mandatory window, result caps, and smallest-query-first as defaults.

**Acceptance.** The field dictionary comes from the real schema, the templates are validated and gated, and the storyline pivot works.

### Milestone 6. Encoding across the five stores, and the routing method

This milestone places the knowledge in the five stores and implements how the agent decides which source and tool answers a question. Routing is the part most likely to be improvised if it is not specified, so build it exactly as described here. Do not drop the model into native tool-calling over the full tool surface, because that is what produced the original failure.

**Routing method**

- **The MCP server is fixed by scope, not chosen from the question.** There is one purple-mcp server for the tenant, bound to the active session. The router never selects a server from the text. It only ever selects a tool inside the already-scoped server. Do not let the question influence server selection, because that reintroduces a cross-tenant path.
- **Intent resolution is an embedding match over the coverage matrix, not free model classification.** Each matrix row carries example questions. Embed them once. At question time, embed the incoming question, take the nearest rows by cosine similarity, and apply a confidence threshold. Above the threshold, use the bound recipe, which names the exact tool and query. If the top two rows are close, treat the intent as ambiguous and either ask one disambiguating question or let a light model pass choose between only those two. Use a local embedding model so the routing decision stays on your infrastructure.
- **The gap-closing set is hard-bound.** Threat count, host lookup, storyline pivot, agent health, and CVE traversal each map to exactly one recipe, with no model discretion and no fallback. "How many threats" resolves to the SentinelOne threat recipe, always.
- **The fallback is constrained, never the full surface.** When nothing matches above the threshold, use the ontology to narrow to the candidate module or modules, pass the model only those tools, and log the call as a candidate new recipe for review. The long tail feeds back into the matrix instead of being re-guessed each time.
- **Every route is logged.** Record the intent, the confidence, the matched example, the chosen recipe, the tool, and the source. That log plus the coverage matrix is the regression set for Milestone 8.

**Tasks**

- [ ] Distil the ontology core, the navigation rules, and the grounding rules into `/agent/context`, kept within the context budget.
- [ ] Enrich each MCP tool description in `/agent/tools`: when to use it, when not to, its parameters, one example, and how it differs from neighbouring tools, especially threats versus Sentry findings versus Deep Visibility. These descriptions are consulted only on the constrained fallback path, not on the primary route.
- [ ] Build the embedding router over the coverage matrix example questions, with the confidence threshold and the ambiguity tie-break, using a local embedding model.
- [ ] Hard-bind the gap-closing intents to their single recipes, bypassing the router's discretion.
- [ ] Implement the constrained fallback: narrow to candidate modules through the ontology, pass only those tools, and log the call as a candidate recipe.
- [ ] Load the field dictionary, the Deep Visibility cookbook, the enum tables, the MITRE maps, and the per-module catalogs into the retrieval store with chunking and retrieval keys, and test that retrieval returns the right chunk.
- [ ] Register the validated recipe library for few-shot or skill use.
- [ ] Stand up the environment memory cache with the tenant sites, groups, key hosts, naming conventions, and token scope, and schedule its refresh.
- [ ] Implement route logging: intent, confidence, matched example, recipe, tool, and source, written on every question.

**Acceptance.** The router resolves the gap-closing set to the correct single recipe every time with no model discretion, ambiguous intents are caught by the threshold rather than guessed, the fallback is limited to ontology-narrowed tools and logs candidates, retrieval returns the correct chunks, the tool descriptions disambiguate the sources, the memory cache is live, and every route is logged.

### Milestone 7. Grounding and interpretation

- [ ] Load the task execution protocol as the operating contract the agent follows on every retrieval.
- [ ] Implement the answer-format contract: every factual answer ends with source, tenant, window, and result count.
- [ ] Implement the empty-result classifier: no activity in window, outside retention, no coverage, or scope error.
- [ ] Implement enum decoding and source naming at response time, so a raw code is never surfaced.
- [ ] Wire the refusals and guardrails: read-only operation, tenant isolation, and refusal of any query that is not validated.

**Acceptance.** Every answer is grounded, empty results are classified rather than called clean, raw codes are never surfaced, and unvalidated queries are refused.

### Milestone 8. Test harness and acceptance

- [ ] Build a harness in `/tests` that runs the coverage matrix against the tenant and scores each answer for correct source, traceability, grounding, and accuracy.
- [ ] Run the regression fixture from Milestone 0 and confirm it passes.
- [ ] For each miss, tune the responsible layer, a tool description, a recipe, the prompt, or a retrieval chunk, then re-run the full matrix, not just the fixed class.
- [ ] Produce an accuracy report.

**Acceptance.** The gap-closing set is fully correct on source and grounding, the agreed pass rate on the full matrix is met on this tenant, the regression passes, and the report is published.

---

## 8. Definition of done for this phase

- The environment map, ontology, coverage matrix, recipe library, and Deep Visibility cookbook are committed and versioned, and all are derived from the live tenant.
- Every gap-closing question class routes to the correct SentinelOne source, and the threat-count regression passes.
- A storyline reconstruction and the core hunt templates run and return valid, MITRE-tagged output.
- Every answer states source, tenant, window, and result count, and empty results are classified.
- The agreed pass rate on the coverage matrix is met on the established tenant.
- The accuracy report is published and the artifacts are frozen for the capabilities phase.

---

## 9. How to work

- Confirm the repo and the MCP tool inventory before you create anything. Bind to real tool names.
- Validate every recipe and template against the live tenant before marking it stable. Never mark stable from a dry run.
- Ask before any broad or expensive Deep Visibility query.
- Keep artifacts model-agnostic so the world model survives a future change of reasoning engine.
- When the exact SentinelOne surface, schema, retention, or tool name is uncertain, discover it from the tenant and the MCP server rather than assuming.
- Commit per milestone with its acceptance checks green before moving on.

When this phase is accepted, the next brief covers agent capabilities, built on top of the grounded understanding this phase produces.
