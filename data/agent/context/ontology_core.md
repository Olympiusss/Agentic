# SentinelOne ontology core (distilled)

One SentinelOne tenant is connected: **CyberVergent Ltd** (account
`1580605217264614055`), one site (`Cybervergent`), three groups (`Product
Engineer`, `Brand and Marketing`, `Admin`). There is no dedicated
account/site/group tool in this MCP server -- hierarchy is recovered from the
`s1AccountId`/`s1SiteId`/`s1GroupId`/`s1ScopePath` fields on inventory items.

## In-scope entities and their source

| Entity | Source module | Real tool binding | Note |
|---|---|---|---|
| **Alert** | SentinelOne Alerts | `search_alerts`, `list_alerts`, `get_alert`, `get_alert_notes`, `get_alert_history`, `get_alert_investigation_report` | **This is the threat source.** There is no separate "Threats" tool in this MCP server -- do not look for one. `search_alerts(first=1)` + read `totalCount` answers any "how many threats/alerts" question. |
| **Vulnerability** | Vulnerability Management | `search_vulnerabilities`, `list_vulnerabilities`, `get_vulnerability`, `get_vulnerability_notes`, `get_vulnerability_history` | Confirmed licensed and populated. Field IDs are flattened camelCase (`cveId`, not `cve.id`). |
| **InventoryItem** | Inventory (endpoints) | `search_inventory_items`, `list_inventory_items`, `get_inventory_item` | Also the source for agent health (`assetStatus`, `agent.upToDate`, `agent.networkStatus`, `agent.isInfected` -- no separate "Agents" tool exists). Uses a REST dict-of-lists filter dialect, different from Alerts/Vulnerabilities/Misconfigurations' `{fieldId, filterType}` dialect. |
| **Storyline** | SentinelOne Alerts | `search_alerts` (fulltext-filter on `storylineId`) | No dedicated tool. Reconstructing an attack chain means reading `storylineId` off one Alert, then filtering Alerts by that ID. |

## Out of scope (probed, confirmed absent or unlicensed -- state this, don't improvise)

- **Misconfiguration** -- probed (`search_misconfigurations(first=1)`), not confirmed populated in this tenant.
- **Policy** -- no endpoint-protection policy tool exists at all in this MCP server.
- **Incident** -- no grouping concept beyond Alert exists.
- **IdentitySecurity**, **CloudSecurity**, **AssetDiscoveryNetwork** -- each probed via `list_inventory_items(surface=...)`, each returned 0 items: not licensed/enabled on this tenant, not "no findings."

## Deep Visibility

Surface confirmed: **PowerQuery** (not legacy Deep Visibility/S1QL 1.0). All 6
core event categories (process, network, dns, file, registry, login) are
queryable. `purple_ai()` is confirmed down on this tenant as of the last
check (`AuthZ error` from the SentinelOne backend, re-verified 2026-07-30) --
the documented `purple_ai() -> powerquery()` path cannot be used until it
recovers. The DV field dictionary and hunt templates in
`data/knowledge/sentinelone/dv_cookbook/` are gated `experimental` for this
reason, not because the fields themselves are wrong.

## Sentry-internal (the control case)

Sentry's own findings store (`sentry-findings` MCP server, a **different**
server than `sentinelone`) is a distinct source: Sentry's own detection
pipeline output, not part of the SentinelOne ontology at all. It is the
correct source only for explicitly Sentry-internal questions ("what has
Sentry flagged"), never for a SentinelOne question. Answering a SentinelOne
question from this store, silently, is the exact failure this phase exists to
fix.

Full detail: `data/knowledge/sentinelone/ontology/sentinelone_ontology.yaml`
(carries `status: draft_pending_review` -- treat as current best knowledge,
not yet analyst-frozen).
