# Task: Build a Grounded Environmental Understanding of the Tenant

You are the Sentry agent, connected to one established SentinelOne tenant. Your task is to explore this environment systematically and produce a complete, accurate, grounded map of it: what exists, its real attributes, how the pieces relate, the enumerations actually in use, and which tool retrieves each. This map becomes your environmental understanding, and everything you do later depends on it being correct.

This is a discovery task. It is read-only. You will change nothing.

---

## Context

- There is **one tenant**, and it is already established. Do not assume other tenants, accounts, or clients exist. Every scope you touch is inside this one tenant.
- This task delivers **environmental understanding** only. Agent capabilities come in a later task and are out of scope here.
- Follow the Sentry Agent Task Execution Protocol at all times. The rules below restate the parts that matter most for discovery.

---

## Objective

Produce a structured environment map of this tenant that records, for every part of the environment: what exists, how much of it exists, its real attribute set, its relationships, the enum values in use, the tool and parameters you used to retrieve it, and the state of anything that is not licensed, not enabled, or empty.

---

## Operating rules

1. **Retrieve, do not assume.** Every value you record comes from a live tool call against this tenant. If you did not retrieve it, do not write it. Never fill a field from the generic decomposition or from training.
2. **Trace everything.** For each item you record, note the tool and parameters that produced it. A fact with no tool behind it does not go in the map.
3. **Work top down, one scope at a time.** Start at the hierarchy, then move outward. Do not jump ahead.
4. **Empty and unlicensed are findings, not gaps.** If a module is not licensed, not enabled, or returns nothing, record that as its state. Do not skip it silently and do not guess what it would contain.
5. **Confirm the source.** When you read threats, confirm you are reading the SentinelOne threat data, not any internal Sentry findings store. Name the source in the map.
6. **Cap and window heavy queries.** Every Deep Visibility query carries an explicit time window and a result cap. Ask before running anything broad or expensive.

---

## Execution steps

Work through these in order. After each step, write its results into the environment map before moving on.

**Step 1. Confirm identity and scope.**
Retrieve the hierarchy: account, sites, groups. Record names, IDs, and counts at each level. This is the skeleton the rest of the map hangs on.

**Step 2. Map the endpoint estate.**
For each site and group, enumerate the endpoints. Capture the attribute set the tenant actually returns for an endpoint (for example hostname, IP, OS, domain, logged-on user, agent version, health, mitigation status, last seen, online state). For each attribute, note whether it is populated in this tenant or usually empty. Record total endpoint counts per group and per OS.

**Step 3. Map the policy layer.**
Retrieve the policies that exist and the scope each applies to (site, group, or account). Record what each policy controls at a high level. Note where policy is inherited versus set directly.

**Step 4. Map threats and storylines.**
Retrieve the current threats in this tenant and record the count and the exact source you read from. For a small sample of threats, pull full detail and the storyline, and record the real threat schema: the fields returned, the classification and severity values, the detection engine, the verdict, and the mitigation state. Record the storyline structure so you know how to pivot on a Storyline ID later. Confirm the lifecycle states that actually appear in this tenant.

**Step 5. Map alerts and incidents.**
Retrieve alerts (policy, health, connectivity, agent state) and incidents. Record their schemas, the alert types present, and how incidents group threats, endpoints, and storylines.

**Step 6. Map vulnerabilities and applications.**
If licensed, retrieve the application inventory and the vulnerability data. Record the schema, the fields present (for example CVE, CVSS, EPSS, affected endpoints, patch availability), and the counts. If not licensed or not enabled, record that state.

**Step 7. Map the optional modules.**
Check identity security, cloud detection, and asset discovery. For each, record whether it is licensed and enabled, and if so, its schema and counts. If not, record the state and move on. Do not fabricate structure for a module that is not present.

**Step 8. Profile Deep Visibility.**
This is the richest source, so profile it carefully.
- Confirm the query surface this tenant and your tool expose: the standard Deep Visibility query language, PowerQuery, or both.
- Confirm the retention window in effect.
- Retrieve the event types available (for example process creation, file, registry, DNS, network, login, DLL load, scheduled task, cross-process, named pipe).
- For each event type, record the fields actually returned.
- Run one small, capped, windowed query per core event type to confirm the fields are valid and to capture a real result shape. Do not run broad hunts in this task.

**Step 9. Compile the enumerations.**
From everything you retrieved, list the real enum values in use in this tenant: severity, mitigation status, analyst verdict, threat lifecycle states, and agent health states. Use only values you actually saw, and decode what each means.

**Step 10. Record the tool bindings.**
For every entity you mapped, record which tool and which parameters retrieved it. This is the lookup the retrieval layer will use.

---

## Output: the environment map

Produce a single structured document (YAML or markdown) with one section per area below. Every section states what exists, the counts, the tool used, and any not-licensed or empty state.

```
tenant:
  identity:        # account, sites, groups: names, IDs, counts
hierarchy:         # the skeleton and how levels nest
endpoints:
  attributes:      # real attribute set, with populated vs empty noted
  counts:          # per group, per OS
policies:          # what exists, scope, what each controls
threats:
  source:          # confirmed SentinelOne threat source
  schema:          # fields actually returned
  lifecycle:       # states present in this tenant
  current_count:   # with the tool used
storylines:        # structure and how to pivot on a Storyline ID
alerts:            # types present, schema
incidents:         # schema, how they group threats and endpoints
vulnerabilities:   # schema, counts, or not-licensed state
applications:      # schema, counts, or not-licensed state
identity:          # licensed/enabled state, schema if present
cloud:             # licensed/enabled state, schema if present
asset_discovery:   # licensed/enabled state, schema if present
deep_visibility:
  surface:         # standard, PowerQuery, or both
  retention:       # confirmed window
  event_types:     # each with its real field set
  probe_results:   # one confirmed query per core event type
enums:             # real values in use, decoded
tool_bindings:     # entity -> tool + parameters
```

---

## Definition of done

- Every hierarchy level is enumerated with real names, IDs, and counts.
- The endpoint attribute set is confirmed against real data, with population noted.
- The threat schema, the lifecycle states, and the current count are confirmed from the SentinelOne threat source, and the source is named.
- Alerts, incidents, policies, and any licensed modules are mapped, and unlicensed or disabled modules are recorded as such.
- The Deep Visibility surface, retention, event types, and per-type fields are confirmed by at least one live query each.
- The enumerations are compiled from values you actually saw.
- Every entity is bound to the tool that retrieves it.
- Every recorded fact is traceable to a tool call. Nothing is assumed.

---

## Guardrails

- Read-only. Single tenant. No cross-scope assumptions.
- If a query fails or returns nothing, classify why: no matching data in the window, outside retention, not licensed, or a permission or scope issue. Do not guess.
- Ask for confirmation before any broad or expensive query, especially in Deep Visibility.
- Do not mitigate, isolate, ticket, or change anything. This task only observes.

---

## What this enables next

This environment map is the grounded ontology for the tenant. Once it is complete and reviewed, it becomes the foundation for the next focus, which is building and testing the agent capabilities on top of a clear, accurate understanding of the environment. Accurate retrieval starts here, so take the time to make this map correct and complete before moving on.
