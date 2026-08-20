# Regression fixture: threat/alert-count source routing

Encodes the failure this whole phase exists to fix (`Sentry_AgenticSOC_Build_Brief_for_Claude.md` §2, `Sentry_Agent_Task_Execution.md` §8.1): asked "how many threats exist," the agent answered from Sentry's own internal findings store (0) instead of SentinelOne, with unearned confidence. This fixture is the Milestone 8 harness's first, non-negotiable regression case.

## Case

- **question**: "How many threats/alerts exist in the environment?" (and paraphrases: "how many threats this week", "any active threats right now")
- **expected_source**: SentinelOne Alerts
- **forbidden_source**: Sentry's internal findings store
- **expected_tool_call**: `search_alerts` with `first=1`, reading `totalCount` from the response — this is the tool's own documented pattern for count-only questions (see `data/knowledge/sentinelone/mcp_tools.md`), not a `list_alerts` full fetch or an assumed "threats" tool that doesn't exist on this server.
- **expected_answer_shape**: states the count in natural language (using the user's own word, "threat," not "alert" — see the post-Phase-2 wording fix below) and ends with the grounding line `Source: <system/module> · Client: <name>` — window/count live in the body prose, not repeated as raw structured fields (simplified post-Phase-2, confirmed product decision: the original `· Window: <range> · Results: <count>` suffix read as too robotic for a conversational product). A genuinely zero count is still classified, never silently dropped — for the common case (no matching activity) that's already implicit in a plain "no threats" sentence; for a more specific classification (not licensed, outside retention, a scope/permission error) the reason is folded into the body as a short clause instead of a separate structured field.

## Wrong (the original failure)

> "0 findings." — answered from Sentry's internal findings store, padded with generic caveats about detection coverage. Wrong source, no grounding line, empty result read as a clean environment.

## Right

When threats exist (values illustrative):

```
<Client> has 14 threats in the last 7 days.
Source: SentinelOne Alerts · Client: <name>
```

When the count is genuinely zero:

```
No threats are recorded on <Client> in the last 7 days.
Source: SentinelOne Alerts · Client: <name>
```

When the count is zero for a more specific reason (illustrative, not this recipe's current behavior on this tenant):

```
No threats are recorded on <Client> in the last 7 days (outside this tenant's retention window).
Source: SentinelOne Alerts · Client: <name>
```

## Pass criteria (for the Milestone 8 harness)

1. The routed tool call targets `search_alerts` (or a stable recipe wrapping it), never any Sentry-internal findings tool, for this question class.
2. The response names the source explicitly as "SentinelOne Alerts."
3. The response includes `Source:` and `Client:` — the load-bearing traceability anchor (which system answered, which tenant); window/count are stated in the body prose instead of repeated as separate structured fields.
4. A zero result is classified (per `Sentry_Agent_Task_Execution.md` §5), never stated as "clean" on its own — checked against the classifier mechanism directly, and folded into the body when the classification is more specific than plain "nothing in this window."
5. This is the gap-closing "threat_count" row in `data/knowledge/sentinelone/coverage_matrix/` (Milestone 3) and is hard-bound to its recipe with no router discretion (Milestone 6).
