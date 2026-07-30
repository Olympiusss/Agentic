# Sentry Agentic SOC: Capabilities Brief for Antigravity

You are Antigravity, the build agent implementing the Sentry agentic SOC. This is the second brief. The first built environmental understanding: a grounded world model of the tenant, the coverage matrix, validated retrieval recipes, the Deep Visibility cookbook, the routing method, and the grounding contract. This brief builds the agent capabilities on top of that foundation.

Read it fully before you start. Confirm the environmental-understanding phase is accepted and its artifacts are frozen before building anything here. If they are not, stop and finish that phase first, because every capability depends on them.

Scope stays narrow. One established tenant. Read-only. Autonomous action stays out.

---

## 1. Context: where the system is now

- The environmental-understanding phase is complete. The agent has a grounded ontology, a prioritised coverage matrix, validated recipes, a Deep Visibility cookbook, a routing method that resolves a question to the correct recipe, and a grounding contract that makes every answer state its source, tenant, window, and count.
- The agent can now answer a single question accurately. It cannot yet perform an investigation.
- Reasoning is Claude through the Anthropic API. SentinelOne is reached through the tenant's purple-mcp server. Confirm the repo and the frozen Phase 2 artifacts before building.

---

## 2. The problem concern

Accurate single-question retrieval is necessary but it is not how a SOC analyst works. Real work is an investigation: a chain of steps that pulls one fact, decides the next question from it, enriches, correlates, and ends in an artifact someone can act on. Ask the current agent "how many threats" and it answers correctly now. Ask it "triage this threat and tell me if it is real and how far it spread" and it has no way to compose the several retrievals and the reasoning that answer needs.

The gap this phase closes is the step from answering questions to performing the analyst's actual workflows, and producing outputs that leave the chat: a triage verdict, a reconstructed attack chain, a hunt result, an exportable report, and a daily environment brief. All of it grounded, all of it read-only.

---

## 3. The solution

A **capability** is a defined, testable competency that composes validated recipes and stable Deep Visibility templates into a multi-step workflow with a grounded output. Every capability has the same shape:

- a trigger, which is an intent class from the coverage matrix,
- a plan, which is an ordered set of references to existing recipes and templates,
- the inputs it resolves against the memory cache,
- a synthesis step, where Claude reasons over the collected results,
- an output contract, which carries the grounding line and separates retrieved fact from interpretation,
- a confidence score,
- a status of stable or experimental.

The central rule is that **a capability composes recipes, it does not invent retrieval**. A capability may only call validated recipes and stable templates through the existing routing and recipe layer. It never calls a raw tool directly. This is what preserves the grounding guarantee at the capability level: a capability output is only as strong as its recipes, and every fact in it still traces to a tool call.

The capabilities are the specialist workforce from the plan of record, each a role the agent performs:

- **Triage.** Score a threat, confirm true or false positive, estimate blast radius.
- **Investigator.** Reconstruct the attack chain and map it to MITRE.
- **Hunter.** Run the proactive hunts and surface hits.
- **Correlator.** Find campaign-level patterns across hosts and time.
- **Threat Intel.** Enrich indicators with reputation, attribution, and technique context.
- **Reporter.** Assemble audit-ready reports, and drive the two output features below.

On top of the workforce sit two output capabilities:

- **Session export.** Any conversation or investigation downloads as a formatted report in PDF, DOCX, Markdown, or JSON, with the grounding lines preserved.
- **Resident 24-hour brief.** On a schedule, the agent runs a defined capability set over the trailing 24 hours on the tenant and produces a brief of what mattered. This is scheduled reporting, an intelligence output, not a response action.

The seventh role, **Responder**, which carries containment and ticketing, is autonomous action and belongs to Objective 2. It is out of scope here. Capabilities may produce a confidence score, and they may recommend a response, but they take no action. Everything surfaces to a human analyst.

---

## 4. Scope and sequence

- **One established tenant only.** No multi-tenant work.
- **Read-only.** Capabilities observe, reason, and report. Nothing mitigates, isolates, tickets, or changes state.
- **Capabilities are within Objective 1.** Autonomous action is Objective 2 and is the next brief after this one.
- Build the capability framework first, then the specialist capabilities, then the outputs, then test.

---

## 5. Constraints and guardrails (non-negotiable)

- A capability calls only validated recipes and stable templates through the routing and recipe layer. No capability calls a raw tool. If a capability needs a retrieval that has no recipe, that retrieval is authored and validated as a recipe first.
- The grounding contract applies to every capability output. State the sources, the tenant, the windows, and the counts. Separate what was retrieved from what is inferred, and label interpretation as interpretation.
- Read-only holds throughout. A capability may recommend an action and attach a confidence score, but it never executes one.
- Keep capability specifications model-agnostic, in YAML and markdown, so the workforce survives a change of reasoning engine. Only the synthesis prompts and tool bindings are engine-specific.
- Anything that runs unattended, which means the 24-hour brief, is windowed, capped, and reviewed before it is scheduled.
- Tenant isolation holds. A capability operates only within the scoped tenant.

---

## 6. Repository and artifact layout

Extend the existing repository. Do not duplicate Phase 2 artifacts, reference them.

```
/capabilities
  registry.yaml          the list of capabilities and their status
  /specs                 one spec per capability (trigger, plan, synthesis, output)
  runner                 executes a capability by composing recipes
/outputs
  /reports               exported session and investigation reports
  /briefs                the daily environment briefs
/schedule                the 24-hour brief scheduler, windowed and capped
/tests
  /capability_fixtures   expected outputs per capability for regression
```

The capability specs reference recipes in `/knowledge/recipes` and templates in `/knowledge/dv_cookbook` by name. They do not restate them.

---

## 7. Step by step implementation plan

Work milestone by milestone. Do not start a milestone until its predecessor's acceptance passes.

### Milestone 0. Capability framework and registry

- [ ] Define the capability schema in `/schemas`: trigger intent, plan as an ordered list of recipe and template references, inputs, synthesis instructions, output contract, confidence, and status.
- [ ] Build the capability runner in `/capabilities`: resolve the intent, load the spec, resolve inputs against the memory cache, execute the plan by calling recipes through the existing routing and recipe layer, collect the grounded results, synthesise with Claude, apply the output contract, and return the output with its confidence.
- [ ] Enforce the composition rule in the runner: a capability can call only registered recipes and stable templates, never a raw tool. Fail closed if a plan references anything else.
- [ ] Create the capability registry and a regression fixture per capability in `/tests/capability_fixtures`.

**Acceptance.** The runner executes a trivial capability end to end, composes only through the recipe layer, refuses a plan that references a raw tool, and produces a grounded output.

### Milestone 1. Triage capability

- [ ] Author the Triage spec: given a threat or finding, compose the threat-detail and hash-reputation recipes, and any related-findings recipe, to judge it.
- [ ] Synthesise a verdict: true positive, false positive, or uncertain, with a severity confirmation and a blast-radius estimate, and a confidence score.
- [ ] Ground the output and separate the retrieved evidence from the judgement.

**Acceptance.** Triage returns a grounded verdict with evidence and confidence on real threats, and never asserts a judgement without the evidence behind it.

### Milestone 2. Investigator capability

- [ ] Author the Investigator spec: compose the storyline pivot recipe and the relevant Deep Visibility templates to reconstruct the attack chain across endpoints.
- [ ] Map the chain to MITRE tactics and techniques, and assemble the affected hosts and a timeline.
- [ ] Ground the output, and offer session export of the investigation.

**Acceptance.** Investigator reconstructs a chain from a real threat, maps it to MITRE, lists the affected hosts, and every step traces to a recipe call.

### Milestone 3. Hunter capability

- [ ] Author the Hunter spec: run the stable Deep Visibility hunt templates over a stated window and aggregate the hits.
- [ ] Tag hits with MITRE techniques and attach the false-positive notes from the cookbook.
- [ ] Respect the window and result caps; never run an experimental template without confirmation.

**Acceptance.** Hunter runs the stable templates on the tenant, returns hits per host with MITRE tags, and stays within the guardrails.

### Milestone 4. Correlator capability

- [ ] Author the Correlator spec: compose the listing and neighbour recipes to find patterns across hosts and time within the tenant.
- [ ] Cluster related findings and surface shared indicators and techniques.
- [ ] Present any campaign hypothesis as interpretation, clearly separated from the retrieved facts.

**Acceptance.** Correlator produces grounded clusters with shared indicators, and labels every hypothesis as interpretation.

### Milestone 5. Threat Intel capability

- [ ] Author the Threat Intel spec: compose the hash-reputation and threat-detail recipes, and any available intelligence recipe, to enrich an indicator.
- [ ] Produce an indicator profile with reputation, technique context, and attribution where supported.
- [ ] Separate sourced enrichment from inference, and record the source of each.

**Acceptance.** Threat Intel enriches a real indicator with grounded reputation and context, and never presents inference as fact.

### Milestone 6. Reporter capability and session export

- [ ] Author the Reporter spec: compose the outputs of other capabilities into an audit-ready report.
- [ ] Implement session export: any conversation or investigation downloads as PDF, DOCX, Markdown, or JSON, preserving the grounding lines and the source list.
- [ ] Store exports under `/outputs/reports`.

**Acceptance.** Reporter assembles a grounded report, and a session exports faithfully in all four formats with the grounding preserved.

### Milestone 7. Resident 24-hour environment brief

- [ ] Author the brief spec: over the trailing 24 hours on the tenant, run a defined capability set covering notable detections, severity movement, new hosts and agent-health changes, hunt hits, and anything the Correlator flags as trending.
- [ ] Synthesise the results into a per-tenant brief, grounded, and store it under `/outputs/briefs`.
- [ ] Implement the scheduler in `/schedule`, windowed and capped, and confirm the owner, format, and delivery channel before enabling it.

**Acceptance.** The brief generates on schedule from real data, is grounded, and is useful enough to start a shift from. It reports only; it takes no action.

### Milestone 8. Capability testing and acceptance

- [ ] Build the capability test harness: run each capability against its fixtures and against the live tenant, and score grounding, accuracy, traceability, and output quality.
- [ ] Confirm no capability bypasses the recipe layer, and confirm read-only operation across the whole set.
- [ ] Tune the responsible spec or recipe for any miss, then re-run the affected capabilities.
- [ ] Produce a capability quality report.

**Acceptance.** Every capability is stable, grounded, and composed only of validated recipes, read-only holds across the set, and the quality report is published.

---

## 8. Definition of done for this phase

- The six read-only capabilities, plus session export and the 24-hour brief, are built, stable, and registered.
- Every capability composes only validated recipes and stable templates, and no capability calls a raw tool.
- Every capability output is grounded and separates retrieved fact from interpretation.
- Session export produces faithful reports in all four formats, and the daily brief generates on schedule and is useful.
- Read-only holds across every capability, and any recommended action carries a confidence score but is not executed.
- The capability quality report is published and the specs are frozen for the next phase.

---

## 9. How to work

- Build the framework and the runner first, then add capabilities one at a time, each as a spec plus a fixture.
- Never call a raw tool from a capability. If a retrieval is missing, author and validate the recipe first, then reference it.
- Validate every capability against the live tenant before marking it stable.
- Separate retrieved fact from interpretation in every output, and record the source of each fact.
- Keep capability specs model-agnostic so the workforce survives a change of reasoning engine.
- Confirm the owner, format, and channel before scheduling the 24-hour brief, and never let it run uncapped.

When this phase is accepted, the next brief covers Objective 2, autonomous action, where the Responder role, ticketing, and containment are built on top of the confidence scores this phase produces, behind a monitored approval period.
