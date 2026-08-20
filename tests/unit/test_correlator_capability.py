"""Unit tests for capabilities/correlator.py (Phase 3, Milestone 4)."""

import json

import pytest

from capabilities import correlator


class FakeMCPClient:
    def __init__(self, responses):
        self._responses = dict(responses)

    def get_connection_status(self):
        return {"sentinelone": True}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        entry = self._responses.get(tool_name)
        if entry is None:
            return {"error": True, "content": [{"type": "text", "text": f"no fake response for {tool_name}"}]}
        text = entry if isinstance(entry, str) else json.dumps(entry)
        return {"error": False, "content": [{"type": "text", "text": text}]}


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


def _patch_synthesis(monkeypatch, text):
    async def _fake(prompt, **kwargs):
        return text, None

    monkeypatch.setattr("capabilities.synthesis.synthesize", _fake)


def _alert(id_, host, classification, storyline_id=None):
    node = {"id": id_, "asset": {"name": host}, "classification": classification}
    if storyline_id:
        node["storylineId"] = storyline_id
    return {"node": node}


@pytest.mark.unit
class TestCorrelatorClustering:
    @pytest.mark.asyncio
    async def test_multi_host_classification_forms_a_cluster(self, monkeypatch):
        alerts = {
            "edges": [
                _alert("a1", "host-a", "RANSOMWARE"),
                _alert("a2", "host-b", "RANSOMWARE"),
                _alert("a3", "host-c", "MANUAL"),
            ]
        }
        _patch_client(monkeypatch, FakeMCPClient({"list_alerts": alerts}))
        _patch_synthesis(monkeypatch, "EVIDENCE:\n...\n\nASSESSMENT:\nCampaign hypothesis: possible ransomware campaign")

        outcome = await correlator.run_correlator(sample_size=10)

        assert outcome.kind == "answered"
        multi_host = [c for c in outcome.clusters if c.kind == "classification_multi_host"]
        assert len(multi_host) == 1
        assert multi_host[0].key == "RANSOMWARE"
        assert set(multi_host[0].hosts) == {"host-a", "host-b"}
        assert "Campaign hypothesis" in outcome.assessment

    @pytest.mark.asyncio
    async def test_single_host_repetition_is_a_host_cluster_not_multi_host(self, monkeypatch):
        alerts = {
            "edges": [
                _alert("a1", "host-a", "MALWARE"),
                _alert("a2", "host-a", "MALWARE"),
            ]
        }
        _patch_client(monkeypatch, FakeMCPClient({"list_alerts": alerts}))
        _patch_synthesis(monkeypatch, "EVIDENCE:\n...\n\nASSESSMENT:\nno cross-host campaign pattern evident")

        outcome = await correlator.run_correlator()

        kinds = {c.kind for c in outcome.clusters}
        assert "classification_multi_host" not in kinds  # only 1 distinct host
        assert "host" in kinds

    @pytest.mark.asyncio
    async def test_no_clusters_short_circuits_before_synthesis_call(self, monkeypatch):
        alerts = {"edges": [_alert("a1", "host-a", "MANUAL")]}  # singleton, no repetition anywhere
        _patch_client(monkeypatch, FakeMCPClient({"list_alerts": alerts}))

        called = []

        async def _fake(prompt, **kwargs):
            called.append(prompt)
            return "unused", None

        monkeypatch.setattr("capabilities.synthesis.synthesize", _fake)

        outcome = await correlator.run_correlator()
        assert outcome.kind == "answered"
        assert outcome.clusters == []
        assert called == []  # never reached the LLM call

    @pytest.mark.asyncio
    async def test_empty_alert_sample_handled(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({"list_alerts": {"edges": []}}))
        outcome = await correlator.run_correlator()
        assert outcome.kind == "answered"
        assert outcome.sample_size == 0
