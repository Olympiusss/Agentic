# Enriched MCP tool descriptions (Milestone 6)

Per-tool guidance -- when to use it, when not to, its real parameters, one
example, and how it differs from its neighbours -- for every tool bound to an
in-scope ontology entity, plus the out-of-scope/unconfigured tools and the
`sentry-findings` server's tools (needed for contrast, since the whole point
of this phase is that a SentinelOne question must never be answered from
there).

**These descriptions are consulted only on the router's constrained fallback
path** (`data/agent/context/navigation_rules.md` step 6), when the model is
reasoning over a short, ontology-narrowed candidate list -- never on the
primary hard-bound or matched-row paths, and never over the full tool
surface. Every field here traces back to a real, live-verified fact recorded
in `data/knowledge/sentinelone/mcp_tools.md` (Milestone 0); nothing is
invented.

| File | Tools covered | MCP server |
|---|---|---|
| `alerts.yaml` | `search_alerts`, `list_alerts`, `get_alert`, `get_alert_notes`, `get_alert_history`, `get_alert_investigation_report` | `sentinelone` |
| `vulnerabilities.yaml` | `search_vulnerabilities`, `list_vulnerabilities`, `get_vulnerability`, `get_vulnerability_notes`, `get_vulnerability_history` | `sentinelone` |
| `inventory.yaml` | `search_inventory_items`, `list_inventory_items`, `get_inventory_item` | `sentinelone` |
| `deep_visibility.yaml` | `powerquery`, `purple_ai`, `get_timestamp_range`, `iso_to_unix_timestamp` | `sentinelone` |
| `cve_database.yaml` | `cve_database_status`, `cve_search_by_id`, `cve_search_by_vendor` | `sentinelone` |
| `misconfigurations.yaml` | `search_misconfigurations`, `list_misconfigurations`, `get_misconfiguration` | `sentinelone` (probed, not confirmed populated on this tenant) |
| `threat_intelligence.yaml` | `threat_intel_by_domain`, `threat_intel_by_hash`, `threat_intel_by_ip`, `threat_intel_by_url`, `threat_intel_get_file_behavior`, `threat_intel_get_file_relationships`, `threat_intel_search` | `sentinelone` (requires `PURPLEMCP_VT_API_KEY`, not currently configured) |
| `sentry_findings.yaml` | `list_findings`, `get_finding` | `sentry-findings` -- a **different** server; the deliberate contrast case |
