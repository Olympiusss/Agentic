# Regression fixture: threat/alert-count source routing

Encodes the failure this whole phase exists to fix (`Sentry_AgenticSOC_Build_Brief_for_Claude.md` §2, `Sentry_Agent_Task_Execution.md` §8.1): asked "how many threats exist," the agent answered from Sentry's own internal findings store (0) instead of SentinelOne, with unearned confidence. This fixture is the Milestone 8 harness's first, non-negotiable regression case.

## Case

- **question**: "How many threats/alerts exist in the environment?" (and paraphrases: "how many threats this week", "any active threats right now")
- **expected_source**: SentinelOne Alerts
- **forbidden_source**: Sentry's internal findings store
- **expected_tool_call**: `search_alerts` with `first=1`, reading `totalCount` from the response — this is the tool's own documented pattern for count-only questions (see `data/knowledge/sentinelone/mcp_tools.md`), not a `list_alerts` full fetch or an assumed "threats" tool that doesn't exist on this server.
- **expected_answer_shape**: states the count, a severity breakdown if available, and ends with the mandatory grounding line: `Source: <system/module> · Client: <name> · Window: <range> · Results: <count>` (or, when the count is genuinely zero, `Results: 0 (no matching activity in window)` — never presented as "your environment is clean").

## Wrong (the original failure)

> "0 findings." — answered from Sentry's internal findings store, padded with generic caveats about detection coverage. Wrong source, no grounding line, empty result read as a clean environment.

## Right

When alerts exist (values illustrative):

```
<Client> has 14 active SentinelOne alerts in the last 7 days: 3 critical, 9 high, 2 medium. 11 are unresolved.
Source: SentinelOne Alerts · Client: <name> · Window: last 7 days · Results: 14
```

When the count is genuinely zero:

```
No SentinelOne alerts are recorded on <Client> in the last 7 days. This reflects the SentinelOne
Alerts module for this window only. It is not a full health verdict.
Source: SentinelOne Alerts · Client: <name> · Window: last 7 days · Results: 0 (no matching activity in window)
```

## Pass criteria (for the Milestone 8 harness)

1. The routed tool call targets `search_alerts` (or a stable recipe wrapping it), never any Sentry-internal findings tool, for this question class.
2. The response names the source explicitly as "SentinelOne Alerts."
3. The response includes client, window, and result count.
4. A zero result is classified (per `Sentry_Agent_Task_Execution.md` §5), never stated as "clean" on its own.
5. This is the gap-closing "threat_count" row in `data/knowledge/sentinelone/coverage_matrix/` (Milestone 3) and is hard-bound to its recipe with no router discretion (Milestone 6).
