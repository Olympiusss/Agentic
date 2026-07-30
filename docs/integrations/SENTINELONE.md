# SentinelOne Integration

Sentry Agentic reaches SentinelOne exclusively through SentinelOne's own
official MCP server, [`purple-mcp`](https://github.com/Sentinel-One/purple-mcp)
(declared in `mcp-config.json` as the `sentinelone` server). It is
**read-only by design** — there is no agent-driven isolation, disconnection,
or other response action through this path.

## Configuration

Set in `.env` (non-secret) and via Settings → Integrations (secret):

```
SENTINELONE_CONSOLE_URL=https://<tenant>.sentinelone.net   # non-secret, .env is fine
SENTINELONE_API_TOKEN=<api-token>                          # secret — set via Settings UI, not .env
```

The token must be scoped to a single **Account** or **Site** — `purple-mcp`
does not support Global-scoped tokens, and only supports one Account/Site
per server instance. This is enforced by SentinelOne server-side, not
visible in the token itself.

## Available tools

Namespaced as `sentinelone_<tool>` in the agent's tool list:

- `sentinelone_powerquery(query, start_datetime, end_datetime)` — Deep Visibility / Singularity Data Lake analytics (see below)
- `sentinelone_purple_ai(query)` — natural-language security questions via Purple AI
- `sentinelone_get_timestamp_range(reference_time?, years|months|weeks|days|hours|minutes|seconds, direction)` — compute a relative time window; returns `{current_time, offset_time}` as ISO 8601 strings. Use this instead of hand-computing dates.
- `sentinelone_iso_to_unix_timestamp(iso_datetime)` — convert an ISO 8601 string to a Unix timestamp
- Alerts: `list_alerts` (GraphQL cursor pagination: `first`, `after`, `view_type` in `ALL|ASSIGNED_TO_ME|UNASSIGNED|MY_TEAM`), `search_alerts`, `get_alert`, `get_alert_notes`, `get_alert_history`, `get_alert_investigation_report`
- Vulnerabilities: `list_vulnerabilities`, `search_vulnerabilities`, `get_vulnerability`, `get_vulnerability_notes`, `get_vulnerability_history`
- Misconfigurations: `list_misconfigurations`, `search_misconfigurations`, `get_misconfiguration`, `get_misconfiguration_notes`, `get_misconfiguration_history`
- Inventory: `list_inventory_items`, `get_inventory_item`, `search_inventory_items` — response shape is `{"data": [...], "pagination": {...}}`, **not** the GraphQL `{"edges": [...]}` shape the other tools use
- External threat intel (CVE, VirusTotal/GTI) — only if `PURPLEMCP_VT_API_KEY` is also set

Tool names, parameters, and this list were confirmed by a live MCP handshake (`initialize` → `list_tools`) against this tenant's `sentinelone` server (v0.7.0), not taken from upstream docs alone — upstream docs describe `powerquery(query, start_time, end_time)`, but the real tool schema on this server requires `start_datetime` / `end_datetime` (ISO 8601, timezone offset required). Re-verify with `list_tools` if `purple-mcp` is ever upgraded.

**Count/pagination fields are not consistently cased across tools** — confirmed live: `search_alerts`/`list_alerts` return **camelCase** (`totalCount`, `pageInfo`), while `search_vulnerabilities`/`list_vulnerabilities`/`search_misconfigurations`/`list_misconfigurations` return **snake_case** (`total_count`, `page_info` with `has_next_page`). Checking the wrong casing silently reads as "field not returned," not an error, and has caused a real undercount in practice (a "1 total vulnerability" finding that was actually 37,863 — see `data/knowledge/sentinelone/mcp_tools.md`'s "Critical corrections" section for the full account).

**`agent.networkStatus`/`isInfected`/`upToDate` on Inventory items are readable but not server-filterable** — `search_inventory_items` rejects both `"networkStatus"` and `"agent.networkStatus"` as filter fields with a real `400: Unknown field` error. Only top-level fields like `assetStatus`/`infectionStatus` are filterable; connectivity-specific questions ("which agents are offline") require fetching broadly (`fetch_fields=ALL`) and classifying `agent.networkStatus` client-side instead.

## Deep Visibility via PowerQuery

Legacy Deep Visibility (`dv/init-query` → `dv/query-status` → `dv/events`,
S1QL 1.0) is being deprecated by SentinelOne (legacy DV + S1QL 1.0
deprecation began Feb 15 2026; full sunset Feb 15 2027). `powerquery()`
against the Singularity Data Lake is the supported replacement and the
only Deep-Visibility-equivalent surface exposed here.

`powerquery()` takes a raw query string with no schema hint from the tool
itself, so an agent given no guidance will guess at field names. What's
confirmed against this tenant (live-tested, not just read from docs):

- `event.category = "process" | limit 1` is valid syntax and returns real
  rows on this tenant.
- **Without an explicit `| columns ...` clause, the result has only two
  columns: `timestamp` and `message`** (an opaque blob) — always add
  `| columns ...` to get structured fields back.
- **A malformed or legacy (S1QL 1.0-style) field name does not just return
  an error — it can close the MCP connection outright**, ending the whole
  session. Don't guess-and-retry rapidly with unfamiliar field names in
  the same conversation; if a query fails, treat it as a hard stop rather
  than trying variations blind.
- **`sentinelone_purple_ai` is confirmed down on this tenant** as a live,
  recurring finding (last re-checked 2026-07-30; returns an `AuthZ error`
  from the SentinelOne backend). It is the documented way to get a
  PowerQuery string generated from natural language rather than
  hand-composing one — do not fall back to it expecting it to work until
  this is independently re-confirmed working.
- Always compute the window with `sentinelone_get_timestamp_range` (or
  `sentinelone_iso_to_unix_timestamp` for conversions) rather than hand-writing
  ISO strings, and always pass both `start_datetime` and `end_datetime` —
  both are required, and an unbounded query against the data lake is
  expensive and slow.

**Example (verified working on this tenant):**

```
event.category = "process" | columns event.time, endpoint.name, process.name, process.cmdline | limit 20
```

Beyond `event.category` and the bare query above, exact dotted field names
(e.g. for network/DNS/file events, or additional process columns) have
**not** been confirmed against this tenant's live schema — SentinelOne's
PowerQuery field set can vary by tenant/module licensing. Before relying on
a new field name, probe it with a small, capped query
(`... | columns <field> | limit 1`) rather than assuming it exists, given
the crash-on-bad-field behavior above.

## Full knowledge base

A much richer, live-verified world model for this tenant exists in
`data/knowledge/sentinelone/` (tool inventory, environment map, ontology,
coverage matrix, retrieval recipes, DV field dictionary/hunt templates,
an embedding-based router, and a grounding/interpretation layer) and
`data/agent/` (distilled context, per-tool guidance, the task execution
protocol). None of it is wired into `services/claude_service.py`'s live
system prompt or tool-dispatch loop yet — that's the next phase's job —
but consult it before improvising a query or assuming a fact about this
tenant. Accuracy report: `data/knowledge/sentinelone/coverage_matrix/accuracy_report.md`.

## Verifying end-to-end

1. Confirm the server is enabled: Settings → Integrations → SentinelOne, or `GET /api/mcp/servers/status`.
2. Check `data/mcp_tools_cache.json` contains a `sentinelone` entry with `powerquery` among its tools.
3. In chat, ask a Deep-Visibility-shaped question (e.g. "show me process execution events from the last hour on `<hostname>`") and confirm the agent calls `sentinelone_powerquery` with a bounded time range, not a guess with no tool call.
