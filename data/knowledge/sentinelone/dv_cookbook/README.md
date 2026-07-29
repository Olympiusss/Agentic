# Deep Visibility / PowerQuery cookbook (Milestone 5 — populated)

**`purple_ai()` failed systemically this session** — confirmed via a live diagnostic probe using the tool's own documented example question ("Is APT-1337 in my environment?") verbatim, not a phrasing issue on this project's side. Every artifact below was built by hand-composing PowerQuery instead of the tool's documented `purple_ai() → powerquery()` path, per explicit user direction, with each field/query tested live and every crash-risk isolated to its own connection (a bad field name can close the whole MCP session outright — confirmed in Phase 1). Nothing here is marked `stable` on the strength of hand-composition alone; the hunt templates and field dictionary stay `experimental` until `purple_ai()` is available to generate and verify them the documented way.

## `field_dictionary.yaml`

Built by `scripts/build_dv_field_dictionary.py`. Real, confirmed fields per event category, each tested with an isolated `| columns <field>` probe:

| Category | Confirmed fields | Notes |
|---|---|---|
| `process` | `event.time`, `endpoint.name`, `process.name`, `process.cmdline` | |
| `dns` | `event.time`, `endpoint.name`, `event.dns.request` | |
| `file` | `event.time`, `endpoint.name`, `file.path` | |
| `registry` | `event.time`, `endpoint.name`, `registry.keyPath` | |
| `network` | none confirmed | No data in the 24h probe window (consistent with Milestone 1's finding) — candidate fields untestable, not guessed. |
| `login` | none confirmed | Same as `network`. |

No crashes occurred across any candidate field tested.

## Hunt templates (6, one per core pattern)

Built by `scripts/build_dv_hunt_templates.py`, each validated against `data/schemas/dv_template.schema.json`, all `status: experimental` (never `stable` without `purple_ai()` verification), all ran without error on a real 24h, capped (`limit: 5`) live query:

| Template | Hunt pattern | MITRE | Confidence |
|---|---|---|---|
| `lolbin_powershell_execution` | living_off_the_land | T1059.001 | Reasonable — uses confirmed `process.name`/`process.cmdline` |
| `credential_access_lsass_reference` | credential_access | T1003.001 | Weak — literal-string cmdline match will miss most real LSASS-dumping techniques |
| `persistence_registry_run_keys` | persistence | T1547.001 | Reasonable — uses confirmed `registry.keyPath` |
| `process_injection_rundll32_proxy` | process_injection | T1055 | **Weakest** — no cross-process/API-call field was confirmed; this only proxies via a commonly-abused LOLBin name |
| `lateral_movement_psexec_proxy` | lateral_movement | T1021.002 | Coarse — no network-category fields were confirmed, so this is a command-line proxy only |
| `exfiltration_dns_baseline` | exfiltration / C2 | T1048, T1071.004 | Coarse baseline — no string-length/entropy function confirmed, so this isn't a real DNS-tunneling detector yet |

None were independently triaged for true/false-positive rate this session (`triage_status` on each template says so explicitly) — a single capped run's output was only checked for "did it run and return something plausible."

## Storyline pivot (extended)

`../recipes/storyline_pivot.yaml` now has a second stage sweeping Deep Visibility. Three candidate correlation fields were tested live, isolated per connection: `storylineId` and `storyline.id` both ran without error but returned no real match; **`src.process.storyline.id` was confirmed to return real data** and is the field now used in the recipe. An endpoint+time-window fallback (using only confirmed fields) was also tested and works, in case the direct field ever stops matching. Caught and fixed a real bug during development: the first version's matching logic treated an empty/blank result as "the field worked" (a blank string vacuously satisfies "doesn't contain 'Match Count: 0'"), which picked the wrong candidate field before the fix.

## What's still open

- Re-run both scripts once `purple_ai()` is confirmed working again, to get the documented natural-language-generated queries and promote what validates to `stable`.
- `network` and `login` categories remain unconfirmed for lack of data in the observed window — re-probe once traffic/logins occur in a future window, don't guess field names now.
- No independent false-positive triage was performed on any hunt template.
