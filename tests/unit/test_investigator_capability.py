"""Unit tests for capabilities/investigator.py (Phase 3, Milestone 2)."""

import json

import pytest

from capabilities import investigator


def _ok(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"error": False, "content": [{"type": "text", "text": text}]}


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
        return _ok(value)


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


def _patch_synthesis(monkeypatch, text):
    async def _fake_synthesize(prompt, **kwargs):
        return text, None

    monkeypatch.setattr("capabilities.synthesis.synthesize", _fake_synthesize)


ALERT_ID = "019fc64e-b780-7c21-8573-9bcf7ad7fb81"
STORYLINE_ID = "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"


@pytest.mark.unit
class TestInvestigatorHappyPath:
    @pytest.mark.asyncio
    async def test_reconstructs_chain_with_timeline_and_hosts(self, monkeypatch):
        alert_detail = {
            "id": ALERT_ID,
            "severity": "HIGH",
            "status": "RESOLVED",
            "storylineId": STORYLINE_ID,
        }
        chain = {
            "edges": [
                {"node": {"id": "a1", "name": "LOLBin execution", "severity": "HIGH",
                          "classification": "MALWARE", "detectedAt": "2026-08-01T10:00:00Z",
                          "asset": {"name": "host-a"}}},
                {"node": {"id": "a2", "name": "Lateral movement", "severity": "CRITICAL",
                          "classification": "MALWARE", "detectedAt": "2026-08-01T09:00:00Z",
                          "asset": {"name": "host-b"}}},
            ]
        }
        _patch_client(
            monkeypatch,
            FakeMCPClient({"get_alert": alert_detail, "get_alert_history": {"edges": []}, "search_alerts": chain}),
        )
        _patch_synthesis(monkeypatch, "EVIDENCE:\nstuff\n\nASSESSMENT:\nLikely T1059\nNarrative: chain moved laterally")

        outcome = await investigator.run_investigator(ALERT_ID)

        assert outcome.kind == "answered"
        assert len(outcome.timeline) == 2
        # Sorted chronologically -- 09:00 event first.
        assert outcome.timeline[0]["name"] == "Lateral movement"
        assert outcome.affected_hosts == ["host-a", "host-b"]
        assert "T1059" in outcome.assessment

    @pytest.mark.asyncio
    async def test_no_storyline_skips_storyline_pivot_and_still_answers(self, monkeypatch):
        alert_detail = {"id": ALERT_ID, "severity": "LOW", "status": "NEW", "storylineId": None}
        fake_client = FakeMCPClient({"get_alert": alert_detail, "get_alert_history": {"edges": []}})
        _patch_client(monkeypatch, fake_client)

        outcome = await investigator.run_investigator(ALERT_ID)

        assert outcome.kind == "answered"
        assert "search_alerts" not in fake_client.calls
        assert outcome.timeline == []


@pytest.mark.unit
class TestInvestigatorErrorHandling:
    @pytest.mark.asyncio
    async def test_threat_detail_failure_short_circuits(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await investigator.run_investigator(ALERT_ID)
        assert outcome.kind == "execution_error"

    @pytest.mark.asyncio
    async def test_synthesis_failure_is_caught(self, monkeypatch):
        alert_detail = {"id": ALERT_ID, "severity": "HIGH", "status": "NEW", "storylineId": STORYLINE_ID}
        chain = {"edges": [{"node": {"id": "a1", "name": "x", "severity": "HIGH",
                                     "classification": "MALWARE", "detectedAt": "2026-08-01T10:00:00Z",
                                     "asset": {"name": "host-a"}}}]}
        _patch_client(
            monkeypatch,
            FakeMCPClient({"get_alert": alert_detail, "get_alert_history": {"edges": []}, "search_alerts": chain}),
        )

        async def _fail(prompt, **kwargs):
            return None, "synthesis call failed: boom"

        monkeypatch.setattr("capabilities.synthesis.synthesize", _fail)

        outcome = await investigator.run_investigator(ALERT_ID)
        assert outcome.kind == "execution_error"
        assert "boom" in outcome.error
