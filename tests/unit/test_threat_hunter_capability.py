"""Unit tests for capabilities/threat_hunter.py (Phase 3, Milestone 3)."""

import pytest

from capabilities import threat_hunter


class FakeMCPClient:
    def __init__(self, responses):
        self._responses = dict(responses)
        self.calls = []

    def get_connection_status(self):
        return {"sentinelone": True}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        self.calls.append(tool_name)
        entry = self._responses.get(tool_name)
        if entry is None:
            return {"error": True, "content": [{"type": "text", "text": f"no fake response for {tool_name}"}]}
        value = entry.pop(0) if isinstance(entry, list) else entry
        text = value if isinstance(value, str) else __import__("json").dumps(value)
        return {"error": False, "content": [{"type": "text", "text": text}]}


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


@pytest.mark.unit
class TestThreatHunterConfirmationGate:
    @pytest.mark.asyncio
    async def test_unconfirmed_call_refuses_and_calls_no_tools(self, monkeypatch):
        fake_client = FakeMCPClient({})
        _patch_client(monkeypatch, fake_client)

        outcome = await threat_hunter.run_threat_hunter(
            template_ids=["lolbin_powershell_execution", "recon_commands"], confirmed=False
        )

        assert outcome.kind == "needs_confirmation"
        assert set(outcome.pending_templates) == {"lolbin_powershell_execution", "recon_commands"}
        assert fake_client.calls == []

    @pytest.mark.asyncio
    async def test_confirmed_call_runs_powerquery_per_template(self, monkeypatch):
        fake_client = FakeMCPClient(
            {
                "get_timestamp_range": {"current_time": "2026-08-03T00:00:00Z", "offset_time": "2026-08-02T00:00:00Z"},
                "powerquery": ["Match Count: 3.0\nColumns: 1\nRows: 3", "Match Count: 0.0\nColumns: 1\nRows: 0"],
            }
        )
        _patch_client(monkeypatch, fake_client)

        outcome = await threat_hunter.run_threat_hunter(
            template_ids=["lolbin_powershell_execution", "recon_commands"], confirmed=True, window_hours=24
        )

        assert outcome.kind == "answered"
        assert len(outcome.hits) == 2
        assert fake_client.calls.count("powerquery") == 2
        counts = {h.template_id: h.match_count for h in outcome.hits}
        assert counts["lolbin_powershell_execution"] == 3
        assert counts["recon_commands"] == 0
        # MITRE tags passed through verbatim, not fabricated.
        hit = next(h for h in outcome.hits if h.template_id == "lolbin_powershell_execution")
        assert hit.mitre[0]["technique_id"] == "T1059.001"

    @pytest.mark.asyncio
    async def test_result_cap_is_respected(self, monkeypatch):
        # lolbin_powershell_execution's result_cap is 5 -- report a match
        # count far above that and confirm it gets capped, never reported
        # as if the query returned more than it was allowed to.
        fake_client = FakeMCPClient(
            {
                "get_timestamp_range": {"current_time": "2026-08-03T00:00:00Z", "offset_time": "2026-08-02T00:00:00Z"},
                "powerquery": "Match Count: 500.0\nColumns: 1\nRows: 500",
            }
        )
        _patch_client(monkeypatch, fake_client)

        outcome = await threat_hunter.run_threat_hunter(
            template_ids=["lolbin_powershell_execution"], confirmed=True
        )

        assert outcome.kind == "answered"
        assert outcome.hits[0].match_count == 5  # capped at result_cap

    @pytest.mark.asyncio
    async def test_one_bad_template_does_not_fail_the_whole_run(self, monkeypatch):
        fake_client = FakeMCPClient(
            {
                "get_timestamp_range": {"current_time": "2026-08-03T00:00:00Z", "offset_time": "2026-08-02T00:00:00Z"},
                "powerquery": [{"__error__": "query timeout"}, "Match Count: 1.0\nColumns: 1\nRows: 1"],
            }
        )

        # FakeMCPClient above doesn't understand {"__error__": ...} -- wrap
        # a small custom client here that errors on the first powerquery
        # call and succeeds on the second.
        class SelectiveFailClient:
            def __init__(self):
                self.powerquery_calls = 0

            def get_connection_status(self):
                return {"sentinelone": True}

            async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
                if tool_name == "get_timestamp_range":
                    return {"error": False, "content": [{"type": "text", "text": '{"current_time": "2026-08-03T00:00:00Z", "offset_time": "2026-08-02T00:00:00Z"}'}]}
                if tool_name == "powerquery":
                    self.powerquery_calls += 1
                    if self.powerquery_calls == 1:
                        return {"error": True, "content": [{"type": "text", "text": "query timeout"}]}
                    return {"error": False, "content": [{"type": "text", "text": "Match Count: 1.0\nColumns: 1\nRows: 1"}]}
                return {"error": True, "content": [{"type": "text", "text": "unexpected"}]}

        _patch_client(monkeypatch, SelectiveFailClient())

        outcome = await threat_hunter.run_threat_hunter(
            template_ids=["lolbin_powershell_execution", "recon_commands"], confirmed=True
        )

        assert outcome.kind == "answered"
        assert len(outcome.hits) == 2
        errored = [h for h in outcome.hits if h.error]
        ok = [h for h in outcome.hits if not h.error]
        assert len(errored) == 1
        assert len(ok) == 1
        assert ok[0].match_count == 1
