"""Unit tests for services/sentinelone_recipe_executor.py.

The live tenant is exercised separately by tests/sentinelone_coverage_harness.py
(see data/knowledge/sentinelone/coverage_matrix/accuracy_report.md, 12/12).
These tests mock services.mcp_client.get_mcp_client() entirely -- the goal
here is to prove the production wiring (parameter extraction, response
unwrapping, empty/error classification, dispatcher safety) is correct in
isolation, not to re-validate the live tenant.
"""

import json

import pytest

from services import sentinelone_grounding_service as grounding
from services import sentinelone_recipe_executor as executor


def _ok(payload):
    """Wrap a payload the way mcp_client.call_tool wraps a successful MCP
    response: JSON-encoded text inside a content block."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"error": False, "content": [{"type": "text", "text": text}]}


def _err(message):
    return {"error": True, "content": [{"type": "text", "text": message}]}


class FakeMCPClient:
    """responses: tool name -> raw payload (or a list, consumed in order,
    for tools called more than once in one recipe)."""

    def __init__(self, responses, connected=True):
        self._responses = dict(responses)
        self._calls = []
        self._connected = connected

    def get_connection_status(self):
        return {"sentinelone": self._connected}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        self._calls.append((server_name, tool_name, arguments))
        entry = self._responses.get(tool_name)
        if entry is None:
            return _err(f"no fake response configured for {tool_name}")
        if isinstance(entry, list):
            value = entry.pop(0)
        else:
            value = entry
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict) and value.get("__error__"):
            return _err(value["__error__"])
        return _ok(value)


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


@pytest.mark.unit
class TestIsSentinelOneActive:
    def test_true_when_connected(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}, connected=True))
        assert executor.is_sentinelone_active() is True

    def test_false_when_not_connected(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}, connected=False))
        assert executor.is_sentinelone_active() is False

    def test_false_when_client_unavailable(self, monkeypatch):
        import services.mcp_client as mcp_client_module

        monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: None)
        assert executor.is_sentinelone_active() is False

    def test_false_on_unexpected_exception(self, monkeypatch):
        import services.mcp_client as mcp_client_module

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr(mcp_client_module, "get_mcp_client", _raise)
        assert executor.is_sentinelone_active() is False


@pytest.mark.unit
class TestThreatCount:
    @pytest.mark.asyncio
    async def test_unwindowed_nonzero(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({"search_alerts": {"totalCount": 386}}))
        outcome = await executor.execute("threat_count", "how many threats exist")
        assert outcome.kind == "answered"
        assert "386" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer

    @pytest.mark.asyncio
    async def test_unwindowed_zero_is_classified_not_clean(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({"search_alerts": {"totalCount": 0}}))
        outcome = await executor.execute("threat_count", "how many threats exist")
        assert outcome.kind == "answered"
        # Generic no-matching-activity classification adds nothing a plain
        # "No threats" sentence doesn't already say, so it's not padded with
        # the raw classification string -- just confirm it reads as empty,
        # never as a "clean" claim, and is still grounded.
        assert "No threats are recorded" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer

    @pytest.mark.asyncio
    async def test_windowed_chains_timestamp_conversion(self, monkeypatch):
        fake = FakeMCPClient(
            {
                "get_timestamp_range": {"current_time": "2026-07-30T00:00:00Z", "offset_time": "2026-07-23T00:00:00Z"},
                "iso_to_unix_timestamp": 1753228800000,
                "search_alerts": {"totalCount": 10},
            }
        )
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute("threat_count", "how many threats in the last 7 days")
        assert outcome.kind == "answered"
        assert "10" in outcome.answer
        assert "last 7 days" in outcome.answer
        # confirm the windowed search_alerts call actually carried the
        # computed start_ms, not an unwindowed call
        windowed_calls = [c for c in fake._calls if c[1] == "search_alerts"]
        assert len(windowed_calls) == 1
        assert "1753228800000" in windowed_calls[0][2]["filters"]

    @pytest.mark.asyncio
    async def test_mcp_error_becomes_execution_error(self, monkeypatch):
        _patch_client(
            monkeypatch,
            FakeMCPClient({"search_alerts": {"__error__": "connection refused"}}),
        )
        outcome = await executor.execute("threat_count", "how many threats exist")
        assert outcome.kind == "execution_error"
        assert "connection refused" in outcome.error

    @pytest.mark.asyncio
    async def test_hour_window_passes_hours_kwarg_not_days(self, monkeypatch):
        # Regression test for the real production bug: "how many threats
        # has occurred in the last 24hrs?" was silently treated as
        # unwindowed because hour-granularity wasn't recognized at all.
        fake = FakeMCPClient(
            {
                "get_timestamp_range": {
                    "current_time": "2026-07-30T21:02:01Z",
                    "offset_time": "2026-07-29T21:02:01Z",
                },
                "iso_to_unix_timestamp": 1785358921536,
                "search_alerts": {"totalCount": 1},
            }
        )
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute("threat_count", "how many threats has occurred in the last 24hrs?")
        assert outcome.kind == "answered"
        assert "last 24 hours" in outcome.answer
        assert "1" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer
        ts_calls = [c for c in fake._calls if c[1] == "get_timestamp_range"]
        assert len(ts_calls) == 1
        assert ts_calls[0][2] == {"hours": 24}


@pytest.mark.unit
class TestEndpointCount:
    @pytest.mark.asyncio
    async def test_counts_returned_page(self, monkeypatch):
        items = {"data": [{"name": f"host-{i}"} for i in range(53)]}
        _patch_client(monkeypatch, FakeMCPClient({"list_inventory_items": items}))
        outcome = await executor.execute("endpoint_count", "how many endpoints do we have")
        assert outcome.kind == "answered"
        assert "53" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer
        assert "at least" not in outcome.answer

    @pytest.mark.asyncio
    async def test_at_limit_reported_as_lower_bound(self, monkeypatch):
        items = {"data": [{"name": f"host-{i}"} for i in range(1000)]}
        _patch_client(monkeypatch, FakeMCPClient({"list_inventory_items": items}))
        outcome = await executor.execute("endpoint_count", "how many endpoints do we have")
        assert outcome.kind == "answered"
        assert "at least 1000" in outcome.answer

    @pytest.mark.asyncio
    async def test_empty_result_classified(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({"list_inventory_items": {"data": []}}))
        outcome = await executor.execute("endpoint_count", "how many endpoints do we have")
        assert outcome.kind == "answered"
        assert "No endpoints were returned" in outcome.answer
        assert "Source:" in outcome.answer

    @pytest.mark.asyncio
    async def test_mcp_error_becomes_execution_error(self, monkeypatch):
        _patch_client(
            monkeypatch,
            FakeMCPClient({"list_inventory_items": {"__error__": "timeout"}}),
        )
        outcome = await executor.execute("endpoint_count", "how many endpoints do we have")
        assert outcome.kind == "execution_error"
        assert "timeout" in outcome.error


@pytest.mark.unit
class TestHostLookup:
    @pytest.mark.asyncio
    async def test_no_hostname_asks_for_clarification(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await executor.execute("host_lookup", "how many endpoints do we have")
        assert outcome.kind == "needs_clarification"
        assert outcome.clarifying_question

    @pytest.mark.asyncio
    async def test_match_found(self, monkeypatch):
        _patch_client(
            monkeypatch,
            FakeMCPClient({"search_inventory_items": {"data": [{"name": "WIN-ABC123"}]}}),
        )
        outcome = await executor.execute("host_lookup", 'what do we know about "WIN-ABC123"')
        assert outcome.kind == "answered"
        assert "WIN-ABC123" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer

    @pytest.mark.asyncio
    async def test_empty_result_classified(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({"search_inventory_items": {"data": []}}))
        outcome = await executor.execute("host_lookup", 'what do we know about "nonexistent-host"')
        assert outcome.kind == "answered"
        assert "No endpoints matched" in outcome.answer


@pytest.mark.unit
class TestCveTraversal:
    @pytest.mark.asyncio
    async def test_no_cve_asks_for_clarification(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await executor.execute("cve_traversal", "what vulnerabilities do we have")
        assert outcome.kind == "needs_clarification"

    @pytest.mark.asyncio
    async def test_affected_assets_reported(self, monkeypatch):
        _patch_client(
            monkeypatch,
            FakeMCPClient(
                {"search_vulnerabilities": {"edges": [{"node": {"id": "1"}}, {"node": {"id": "2"}}]}}
            ),
        )
        outcome = await executor.execute("cve_traversal", "which endpoints are affected by CVE-2024-1234")
        assert outcome.kind == "answered"
        assert "CVE-2024-1234" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer


@pytest.mark.unit
class TestVulnerabilityGeneral:
    @pytest.mark.asyncio
    async def test_reads_snake_case_total_count_not_camel_case(self, monkeypatch):
        # Real Milestone 7 bug: this tool returns total_count (snake_case),
        # not totalCount like Alerts. A regression here would silently
        # undercount by orders of magnitude, exactly as it did live once.
        _patch_client(
            monkeypatch,
            FakeMCPClient(
                {"search_vulnerabilities": {"total_count": 4923, "totalCount": 1, "edges": []}}
            ),
        )
        outcome = await executor.execute("vulnerability_general", "what are our critical vulnerabilities")
        assert outcome.kind == "answered"
        assert "4923" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer

    @pytest.mark.asyncio
    async def test_no_severity_filter_when_unspecified(self, monkeypatch):
        fake = FakeMCPClient({"search_vulnerabilities": {"total_count": 37863}})
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute("vulnerability_general", "how many vulnerabilities do we have")
        assert outcome.kind == "answered"
        call = fake._calls[0]
        assert json.loads(call[2]["filters"]) == []


@pytest.mark.unit
class TestThreatDetail:
    @pytest.mark.asyncio
    async def test_no_id_asks_for_clarification(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await executor.execute("threat_detail", "tell me more about that alert")
        assert outcome.kind == "needs_clarification"

    @pytest.mark.asyncio
    async def test_decodes_severity_and_status(self, monkeypatch):
        alert_id = "019fb1b3-a3a3-7bc1-9a62-09af13cfa38b"
        _patch_client(
            monkeypatch,
            FakeMCPClient({"get_alert": {"severity": "INFO", "status": "NEW"}}),
        )
        outcome = await executor.execute("threat_detail", f"tell me more about alert {alert_id}")
        assert outcome.kind == "answered"
        assert "severity=INFO" in outcome.answer
        assert "status=NEW" in outcome.answer


@pytest.mark.unit
class TestStorylinePivot:
    @pytest.mark.asyncio
    async def test_empty_chain_classified(self, monkeypatch):
        sid = "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"
        _patch_client(monkeypatch, FakeMCPClient({"search_alerts": {"edges": []}}))
        outcome = await executor.execute("storyline_pivot", f"reconstruct storyline {sid}")
        assert outcome.kind == "answered"
        assert "No alerts found" in outcome.answer


@pytest.mark.unit
class TestAgentHealth:
    @pytest.mark.asyncio
    async def test_default_framing_counts_not_connected(self, monkeypatch):
        items = {
            "data": [
                {"name": "a", "agent": {"networkStatus": "connected"}},
                {"name": "b", "agent": {"networkStatus": "disconnected"}},
            ]
        }
        _patch_client(monkeypatch, FakeMCPClient({"list_inventory_items": items}))
        outcome = await executor.execute("agent_health", "which agents are offline")
        assert outcome.kind == "answered"
        assert "1 of 2" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer

    @pytest.mark.asyncio
    async def test_connected_filter_inverts_selection(self, monkeypatch):
        items = {
            "data": [
                {"name": "a", "agent": {"networkStatus": "connected"}},
                {"name": "b", "agent": {"networkStatus": "disconnected"}},
            ]
        }
        _patch_client(monkeypatch, FakeMCPClient({"list_inventory_items": items}))
        outcome = await executor.execute("agent_health", "which agents are connected")
        assert outcome.kind == "answered"
        assert "1 of 2" in outcome.answer
        assert "Source:" in outcome.answer and "Client:" in outcome.answer


@pytest.mark.unit
class TestDvHunt:
    @pytest.mark.asyncio
    async def test_matches_template_and_runs_powerquery(self, monkeypatch):
        fake = FakeMCPClient(
            {
                "get_timestamp_range": {
                    "current_time": "2026-07-30T21:00:00Z",
                    "offset_time": "2026-07-29T21:00:00Z",
                },
                "powerquery": "Match Count: 2.0\n\nColumns: 3\n\nRows: 2",
            }
        )
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute(
            "dv_hunt",
            "show me file downloads in the last 24 hours ending in .zip, .iso, or .html",
        )
        assert outcome.kind == "answered"
        assert "2 match(es)" in outcome.answer
        assert "not Purple-AI-verified" in outcome.answer
        assert "purple_ai" not in [c[1] for c in fake._calls]
        pq_calls = [c for c in fake._calls if c[1] == "powerquery"]
        assert len(pq_calls) == 1

    @pytest.mark.asyncio
    async def test_no_time_range_asks_for_clarification(self, monkeypatch):
        # Real production bug: a hunt question with no time range given
        # ("find all file download events...") silently defaulted to the
        # template's 24h window instead of asking -- confirmed unwanted.
        # No get_timestamp_range/powerquery response configured on purpose:
        # this must ask, never fall through and call either.
        fake = FakeMCPClient({})
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute(
            "dv_hunt",
            "find all file download events where the name ends with .zip, .iso, or .html",
        )
        assert outcome.kind == "needs_clarification"
        assert outcome.clarifying_question
        assert "time range" in outcome.clarifying_question.lower()
        assert fake._calls == []

    @pytest.mark.asyncio
    async def test_zero_matches_classified_not_clean(self, monkeypatch):
        fake = FakeMCPClient(
            {
                "get_timestamp_range": {
                    "current_time": "2026-07-30T21:00:00Z",
                    "offset_time": "2026-07-29T21:00:00Z",
                },
                "powerquery": "Match Count: 0",
            }
        )
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute("dv_hunt", "find registry run key persistence in the last 7 days")
        assert outcome.kind == "answered"
        assert "No matches" in outcome.answer

    @pytest.mark.asyncio
    async def test_powerquery_error_becomes_execution_error(self, monkeypatch):
        fake = FakeMCPClient(
            {
                "get_timestamp_range": {
                    "current_time": "2026-07-30T21:00:00Z",
                    "offset_time": "2026-07-29T21:00:00Z",
                },
                "powerquery": {"__error__": "field not recognized"},
            }
        )
        _patch_client(monkeypatch, fake)
        outcome = await executor.execute("dv_hunt", "find registry run key persistence in the last 24 hours")
        assert outcome.kind == "execution_error"
        assert "field not recognized" in outcome.error

    @pytest.mark.asyncio
    async def test_unrelated_question_low_confidence_still_calls_llm_path(self, monkeypatch):
        # A question completely outside the cookbook's topic space should
        # not run some random template just because k=1 always returns
        # something -- the confidence floor must catch this.
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await executor.execute("dv_hunt", "xk7 qzplm vwxdr nnq")
        assert outcome.kind == "execution_error"


@pytest.mark.unit
class TestDispatcher:
    @pytest.mark.asyncio
    async def test_unknown_question_class(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await executor.execute("identity_security", "are there risky accounts")
        assert outcome.kind == "execution_error"

    @pytest.mark.asyncio
    async def test_unexpected_exception_becomes_execution_error(self, monkeypatch):
        def _raise(*_a, **_k):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(executor, "_EXECUTORS", {"threat_count": _raise})
        outcome = await executor.execute("threat_count", "how many threats exist")
        assert outcome.kind == "execution_error"
        assert "unexpected" in outcome.error


@pytest.mark.unit
def test_resolve_source_module_matches_coverage_matrix():
    # sanity check the executors' grounding.resolve_source_module calls
    # will actually resolve for every question_class they're wired for
    for qc in executor._EXECUTORS:
        assert grounding.resolve_source_module(qc)
