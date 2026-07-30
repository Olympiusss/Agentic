"""Shared MCP-client helpers for the SentinelOne discovery/ontology scripts.

Private helper module (leading underscore) -- not a standalone script.
Both ``discover_sentinelone_environment.py`` (Milestone 1) and
``build_sentinelone_ontology.py`` (Milestone 2) need the exact same
stdio connection setup and tool-call wrapping, so it lives here once
rather than duplicated in each script.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from mcp import ClientSession, StdioServerParameters  # noqa: E402

PURPLE_MCP_VERSION = "v0.7.0"
PURPLE_MCP_ARGS = [
    "--from",
    f"git+https://github.com/Sentinel-One/purple-mcp.git@{PURPLE_MCP_VERSION}",
    "purple-mcp",
    "--mode",
    "stdio",
]


def server_params() -> StdioServerParameters:
    token = os.environ.get("SENTINELONE_API_TOKEN")
    url = os.environ.get("SENTINELONE_CONSOLE_URL")
    if not token or not url:
        raise RuntimeError(
            "SENTINELONE_API_TOKEN and SENTINELONE_CONSOLE_URL must be set "
            "(in .env or the environment) to run discovery."
        )
    env = os.environ.copy()
    env["PURPLEMCP_CONSOLE_TOKEN"] = token
    env["PURPLEMCP_CONSOLE_BASE_URL"] = url
    return StdioServerParameters(command="uvx", args=PURPLE_MCP_ARGS, env=env)


class ToolLog:
    """Every tool call made during a run, so each fact derived from it can
    be traced back to exactly what produced it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, tool: str, parameters: dict[str, Any], purpose: str) -> None:
        self.calls.append({"tool": tool, "parameters": parameters, "purpose": purpose})

    def bindings_for(self, *tools: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["tool"] in tools]


async def call(
    session: ClientSession, log: ToolLog, tool: str, parameters: dict[str, Any], purpose: str
) -> Any:
    result = await session.call_tool(tool, parameters)
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    log.record(tool, parameters, purpose)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def edges(payload: Any) -> list[dict[str, Any]]:
    """GraphQL-shaped tools (alerts/vulnerabilities/misconfigurations) return
    {"edges": [{"node": {...}}], "pageInfo": {...}, "totalCount": N}."""
    if isinstance(payload, dict):
        return [e.get("node", {}) for e in payload.get("edges", []) if isinstance(e, dict)]
    return []


def total_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        return payload.get("totalCount")
    return None
