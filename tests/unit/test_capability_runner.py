"""Unit tests for capabilities/runner.py (Phase 3, Milestone 0).

Mirrors tests/unit/test_sentinelone_recipe_executor.py's mocking approach
(FakeMCPClient) -- the goal is to prove the runner's own mechanics
(composition-only enforcement, multi-step execution, grounded output),
not to re-validate the underlying recipes themselves (already covered by
the recipe executor's own unit tests and the live coverage harness).
"""

import json

import pytest

from capabilities import runner


def _ok(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"error": False, "content": [{"type": "text", "text": text}]}


class FakeMCPClient:
    """responses: tool name -> payload, or a list consumed in order for
    repeated calls to the same tool (matches this capability's plan,
    which calls list_inventory_items three times in sequence)."""

    def __init__(self, responses, connected=True):
        self._responses = dict(responses)
        self._connected = connected

    def get_connection_status(self):
        return {"sentinelone": self._connected}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        entry = self._responses.get(tool_name)
        if entry is None:
            return {"error": True, "content": [{"type": "text", "text": f"no fake response for {tool_name}"}]}
        value = entry.pop(0) if isinstance(entry, list) else entry
        return _ok(value)


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


@pytest.mark.unit
class TestEnvironmentSnapshot:
    @pytest.mark.asyncio
    async def test_happy_path_composes_three_recipes_and_grounds_output(self, monkeypatch):
        endpoint_items = {"data": [{"name": f"host-{i}"} for i in range(53)]}
        group_items = {
            "data": [
                {"s1GroupName": "Product Engineer"},
                {"s1GroupName": "Admin"},
            ]
        }
        tenant_items = {
            "data": [
                {"s1AccountName": "CyberVergent Ltd", "s1SiteName": "Cybervergent"},
            ]
        }
        _patch_client(
            monkeypatch,
            FakeMCPClient({"list_inventory_items": [endpoint_items, group_items, tenant_items]}),
        )

        outcome = await runner.run_capability("environment_snapshot", {})

        assert outcome.kind == "answered"
        assert len(outcome.steps) == 3
        for step in outcome.steps:
            assert step.outcome_kind == "answered"
            assert "Source:" in step.answer and "Client:" in step.answer
        assert "53" in outcome.output
        assert "Product Engineer" in outcome.output

    @pytest.mark.asyncio
    async def test_unknown_capability_id_is_execution_error(self):
        outcome = await runner.run_capability("does_not_exist", {})
        assert outcome.kind == "execution_error"
        assert "no capability spec found" in outcome.error


@pytest.mark.unit
class TestCompositionRuleEnforcement:
    def test_raw_tool_reference_is_refused(self):
        plan = [{"type": "tool", "ref": "list_alerts", "name": "raw tool attempt"}]
        reason = runner._validate_plan_composition(plan)
        assert reason is not None
        assert "raw tool" in reason

    def test_unknown_recipe_reference_is_refused(self):
        plan = [{"type": "recipe", "ref": "not_a_real_recipe", "name": "bogus"}]
        reason = runner._validate_plan_composition(plan)
        assert reason is not None
        assert "not_a_real_recipe" in reason

    def test_unknown_template_reference_is_refused(self):
        plan = [{"type": "template", "ref": "not_a_real_template", "name": "bogus"}]
        reason = runner._validate_plan_composition(plan)
        assert reason is not None

    def test_known_stable_recipe_passes(self):
        plan = [{"type": "recipe", "ref": "endpoint_count", "name": "endpoint count"}]
        assert runner._validate_plan_composition(plan) is None

    @pytest.mark.asyncio
    async def test_run_capability_refuses_before_executing_when_plan_is_invalid(self, monkeypatch, tmp_path):
        # A spec with a raw-tool step must be refused end-to-end, never
        # partially executed -- write a throwaway spec file rather than a
        # committed fixture, since this is deliberately an invalid plan.
        bad_spec = {
            "capability_id": "bad_capability",
            "role": "framework",
            "trigger_intent": "bad_capability",
            "plan": [{"type": "tool", "ref": "list_alerts", "name": "raw tool attempt"}],
            "inputs": [],
            "synthesis": "none",
            "output_contract": {"separates_fact_from_interpretation": True},
            "status": "experimental",
        }
        spec_path = tmp_path / "bad_capability.yaml"
        import yaml

        spec_path.write_text(yaml.safe_dump(bad_spec), encoding="utf-8")
        monkeypatch.setattr(runner, "SPECS_DIR", tmp_path)

        # No MCP client patched at all -- if the runner tried to execute
        # before refusing, it would raise/error instead of cleanly refusing.
        outcome = await runner.run_capability("bad_capability", {})
        assert outcome.kind == "refused"
        assert "raw tool" in outcome.error
