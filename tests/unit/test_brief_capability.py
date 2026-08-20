"""Unit tests for capabilities/brief.py (Phase 3, Milestone 7)."""

import json

import pytest

from capabilities import brief


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
        text = value if isinstance(value, str) else json.dumps(value)
        return {"error": False, "content": [{"type": "text", "text": text}]}


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


def _patch_synthesis(monkeypatch, text):
    async def _fake(prompt, **kwargs):
        return text, None

    monkeypatch.setattr("capabilities.synthesis.synthesize", _fake)


@pytest.mark.unit
class TestRunBrief:
    @pytest.mark.asyncio
    async def test_composes_three_recipes_and_synthesizes(self, monkeypatch):
        responses = {
            "search_alerts": [{"totalCount": 5}, {"totalCount": 1}, {"totalCount": 20}],
            "list_inventory_items": {"data": [{"name": f"host-{i}", "agent": {"networkStatus": "connected"}} for i in range(53)]},
        }
        fake_client = FakeMCPClient(responses)
        _patch_client(monkeypatch, fake_client)
        _patch_synthesis(monkeypatch, "EVIDENCE:\n...\n\nASSESSMENT:\nSummary: quiet shift, no notable detections")

        outcome = await brief.run_brief()

        assert outcome.kind == "answered"
        assert len(outcome.evidence) == 3
        assert "quiet shift" in outcome.summary
        assert outcome.generated_at is not None

    @pytest.mark.asyncio
    async def test_one_recipe_failure_short_circuits_whole_brief(self, monkeypatch):
        # incident_status calls search_alerts 3x; make it fail entirely.
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await brief.run_brief()
        assert outcome.kind == "execution_error"
