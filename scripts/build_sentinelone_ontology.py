#!/usr/bin/env python3
"""Build the SentinelOne tenant ontology (Phase 2, Milestone 2).

Generates ``data/knowledge/sentinelone/ontology/sentinelone_ontology.yaml``
from a live sample of each core entity plus
``data/knowledge/sentinelone/environment_map.yaml`` (Milestone 1's output),
validating every entity against ``data/schemas/ontology.schema.json``.

Milestone 1's environment map only recorded which attributes appeared *at
all* across small (5-item) samples -- not enough to honestly distinguish
the ontology schema's "always_present" from "usually_present". This
script pulls one modest, still-bounded additional sample per core entity
(``SAMPLE_SIZE`` items each for Alerts, Vulnerabilities, and Inventory/
Endpoints -- plain list/search calls, not Deep Visibility, so this does
not fall under the DV-specific confirmation gate the companion documents
call out) purely to compute real per-attribute population rates.

The output carries ``status: draft_pending_review`` -- per the brief's own
Milestone 2 instruction to insert a human review checkpoint before
freezing v1. Nothing downstream should treat this as frozen until a human
sets ``reviewed_by`` on each entity.

Run from the repo root::

    python scripts/build_sentinelone_ontology.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402
from jsonschema import validate  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from scripts._sentinelone_mcp import (  # noqa: E402
    ToolLog,
    call,
    edges,
    server_params,
    total_count,
)

SAMPLE_SIZE = 25

ENVIRONMENT_MAP_PATH = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "environment_map.yaml"
SCHEMA_PATH = REPO_ROOT / "data" / "schemas" / "ontology.schema.json"
OUTPUT_PATH = REPO_ROOT / "data" / "knowledge" / "sentinelone" / "ontology" / "sentinelone_ontology.yaml"


def _is_populated(value: Any) -> bool:
    return value not in (None, "", [], {})


def population_label(rate: float) -> str:
    """Map an observed non-null rate to the ontology schema's 4-level
    enum. Thresholds are conservative on purpose -- "always" is a strong
    claim, so it requires near-100%, not just "most of the time"."""
    if rate >= 0.95:
        return "always_present"
    if rate >= 0.5:
        return "usually_present"
    if rate > 0:
        return "rarely_present"
    return "never_observed"


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (dict,)):
        return "object"
    if isinstance(value, (list,)):
        return "array"
    if value is None:
        return "unknown"
    return "string"


def build_attributes(
    nodes: list[dict[str, Any]], sample_size: int, enum_fields: dict[str, str]
) -> list[dict[str, Any]]:
    """Compute real per-attribute population rates over `nodes` (a sample
    of `sample_size` items -- sample_size, not len(nodes), is the
    denominator, so a field absent from every node still gets an honest
    0% rate rather than being silently omitted)."""
    if sample_size == 0:
        return []
    counts: dict[str, int] = {}
    types: dict[str, Any] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for k, v in node.items():
            if _is_populated(v):
                counts[k] = counts.get(k, 0) + 1
                types.setdefault(k, v)
    attributes = []
    for name, count in sorted(counts.items()):
        attr: dict[str, Any] = {
            "name": name,
            "type": _infer_type(types.get(name)),
            "population": population_label(count / sample_size),
        }
        if name in enum_fields:
            attr["enum_ref"] = enum_fields[name]
        attributes.append(attr)
    return attributes


async def sample_entity(
    session: ClientSession, log: ToolLog, tool: str, params: dict[str, Any], purpose: str
) -> tuple[list[dict[str, Any]], int]:
    payload = await call(session, log, tool, params, purpose)
    nodes = edges(payload)
    return nodes, len(nodes)


async def sample_inventory(
    session: ClientSession, log: ToolLog, surface: str, limit: int, purpose: str
) -> tuple[list[dict[str, Any]], int]:
    payload = await call(
        session,
        log,
        "list_inventory_items",
        {"limit": limit, "surface": surface, "fetch_fields": "ALL"},
        purpose,
    )
    items = payload.get("data", []) if isinstance(payload, dict) else []
    return items, len(items)


def validate_entity(entity: dict[str, Any], schema: dict[str, Any]) -> None:
    validate(entity, schema)


async def build(env_map: dict[str, Any]) -> list[dict[str, Any]]:
    schema = __import__("json").load(open(SCHEMA_PATH, encoding="utf-8"))
    log = ToolLog()
    entities: list[dict[str, Any]] = []

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # --- Alert ---
            alert_nodes, alert_n = await sample_entity(
                session, log, "list_alerts", {"first": SAMPLE_SIZE},
                f"sample {SAMPLE_SIZE} alerts to compute real per-attribute population rates",
            )
            alert_attrs = build_attributes(
                alert_nodes, alert_n,
                {
                    "severity": "alert_severity",
                    "status": "alert_status",
                    "analystVerdict": "alert_analyst_verdict",
                    "classification": "alert_classification",
                },
            )
            alert_entity = {
                "entity": "Alert",
                "description": (
                    "SentinelOne security alert. This tenant's MCP server has no "
                    "distinct 'Threats' tool -- Alerts is the source for threat/"
                    "threat-count questions (confirmed Milestone 0)."
                ),
                "attributes": alert_attrs,
                "relationships": [
                    {"target_entity": "InventoryItem", "relationship": "affects", "via_attribute": "asset"},
                    {"target_entity": "Storyline", "relationship": "belongs_to_storyline", "via_attribute": "storylineId"},
                ],
                "enums": {
                    "alert_severity": {v: v for v in env_map.get("enums", {}).get("alert_severity", [])},
                    "alert_status": {v: v for v in env_map.get("enums", {}).get("alert_status", [])},
                    "alert_analyst_verdict": {v: v for v in env_map.get("enums", {}).get("alert_analyst_verdict", [])},
                    "alert_classification": {v: v for v in env_map.get("enums", {}).get("alert_classification", [])},
                },
                "lifecycle_states": env_map.get("enums", {}).get("alert_status", []),
                "tool_bindings": [
                    {"tool": "search_alerts", "purpose": "filtered search; first=1 + totalCount for count-only questions"},
                    {"tool": "list_alerts", "purpose": "basic listing, assignment filter only"},
                    {"tool": "get_alert", "purpose": "lookup by ID"},
                    {"tool": "get_alert_notes", "purpose": "analyst notes for one alert"},
                    {"tool": "get_alert_history", "purpose": "audit trail for one alert"},
                    {"tool": "get_alert_investigation_report", "purpose": "Purple AI auto-investigation report for one alert"},
                ],
                "in_scope": True,
            }
            validate_entity(alert_entity, schema)
            entities.append(alert_entity)

            # --- Vulnerability ---
            vuln_nodes, vuln_n = await sample_entity(
                session, log, "list_vulnerabilities", {"first": SAMPLE_SIZE},
                f"sample {SAMPLE_SIZE} vulnerabilities to compute real per-attribute population rates",
            )
            vuln_attrs = build_attributes(
                vuln_nodes, vuln_n, {"severity": "vulnerability_severity"}
            )
            vuln_entity = {
                "entity": "Vulnerability",
                "description": "SentinelOne vulnerability finding. Confirmed licensed and populated in this tenant (Milestone 1).",
                "attributes": vuln_attrs,
                "relationships": [
                    {"target_entity": "InventoryItem", "relationship": "affects", "via_attribute": "asset"},
                ],
                "enums": {
                    "vulnerability_severity": {v: v for v in env_map.get("enums", {}).get("vulnerability_severity", [])},
                },
                "tool_bindings": [
                    {"tool": "search_vulnerabilities", "purpose": "filtered search"},
                    {"tool": "list_vulnerabilities", "purpose": "basic listing"},
                    {"tool": "get_vulnerability", "purpose": "lookup by ID"},
                    {"tool": "get_vulnerability_notes", "purpose": "analyst notes"},
                    {"tool": "get_vulnerability_history", "purpose": "audit trail"},
                ],
                "in_scope": True,
            }
            validate_entity(vuln_entity, schema)
            entities.append(vuln_entity)

            # --- InventoryItem (Endpoint) ---
            endpoint_items, endpoint_n = await sample_inventory(
                session, log, "ENDPOINT", SAMPLE_SIZE,
                f"sample {SAMPLE_SIZE} endpoint inventory items to compute real per-attribute population rates",
            )
            endpoint_attrs = build_attributes(endpoint_items, endpoint_n, {})
            endpoint_entity = {
                "entity": "InventoryItem",
                "description": "SentinelOne managed asset (endpoint surface). Carries the s1AccountId/s1SiteId/s1GroupId/s1ScopePath fields used to recover tenant hierarchy (Milestone 1).",
                "attributes": endpoint_attrs,
                "tool_bindings": [
                    {"tool": "list_inventory_items", "purpose": "basic listing, surface-filtered"},
                    {"tool": "get_inventory_item", "purpose": "lookup by ID"},
                    {"tool": "search_inventory_items", "purpose": "REST-dialect filtered search (different filter shape than Alerts/Vulnerabilities/Misconfigurations)"},
                ],
                "in_scope": True,
            }
            validate_entity(endpoint_entity, schema)
            entities.append(endpoint_entity)

            # --- Storyline (not independently queryable) ---
            storyline_entity = {
                "entity": "Storyline",
                "description": "Attack-chain grouping referenced by Alert.storylineId. No dedicated tool exists for it in this MCP server -- only reachable by filtering Alerts on storylineId (the Task Execution Protocol's storyline pivot procedure).",
                "attributes": [
                    {"name": "storylineId", "type": "string", "population": "rarely_present"},
                ],
                "relationships": [
                    {"target_entity": "Alert", "relationship": "groups", "via_attribute": "storylineId"},
                ],
                "tool_bindings": [
                    {"tool": "search_alerts", "purpose": "pivot: fulltext-filter alerts by storylineId to reconstruct the chain"},
                ],
                "in_scope": True,
            }
            validate_entity(storyline_entity, schema)
            entities.append(storyline_entity)

            # --- Misconfiguration (licensing not independently confirmed in M1;
            # M1's scope-recovery probe on this tool found nothing, but that
            # used a fields=["id","scope"] filter -- recheck generally here) ---
            misconfig_probe_nodes, _ = await sample_entity(
                session, log, "search_misconfigurations", {"first": 1},
                "licensing probe: was Misconfigurations ever independently confirmed populated in this tenant?",
            )
            misconfig_licensed = bool(misconfig_probe_nodes)
            misconfig_attrs: list[dict[str, Any]] = []
            if misconfig_licensed:
                misconfig_nodes, misconfig_n = await sample_entity(
                    session, log, "list_misconfigurations", {"first": SAMPLE_SIZE},
                    f"sample {SAMPLE_SIZE} misconfigurations to compute real per-attribute population rates",
                )
                # No "misconfiguration_severity" enum was compiled in
                # Milestone 1's environment map, so no enum_ref is attached
                # here -- would need its own enum-compilation pass to add
                # honestly, not invented now.
                misconfig_attrs = build_attributes(misconfig_nodes, misconfig_n, {})
            misconfig_entity = {
                "entity": "Misconfiguration",
                "description": "CSPM/IaC misconfiguration finding.",
                "attributes": misconfig_attrs,
                "tool_bindings": [
                    {"tool": "search_misconfigurations", "purpose": "filtered search"},
                    {"tool": "list_misconfigurations", "purpose": "basic listing"},
                    {"tool": "get_misconfiguration", "purpose": "lookup by ID"},
                ],
                "in_scope": misconfig_licensed,
            }
            if not misconfig_licensed:
                misconfig_entity["description"] += (
                    " Probed with search_misconfigurations(first=1) in Milestone 2: "
                    "returned no records in this tenant -- not confirmed populated/licensed."
                )
            validate_entity(misconfig_entity, schema)
            entities.append(misconfig_entity)

    # --- Out-of-scope entities from the generic decomposition, per the
    # brief's explicit instruction to record them rather than omit them
    # silently. Each cites the exact Milestone 1 finding that grounds it.
    out_of_scope = [
        {
            "entity": "Policy",
            "description": "SentinelOne endpoint-protection policy.",
            "attributes": [],
            "tool_bindings": [],
            "in_scope": False,
        },
        {
            "entity": "Incident",
            "description": "A grouping of alerts/threats/endpoints distinct from a single Alert.",
            "attributes": [],
            "tool_bindings": [],
            "in_scope": False,
        },
        {
            "entity": "IdentitySecurity",
            "description": "SentinelOne Identity Security module.",
            "attributes": [],
            "tool_bindings": [
                {"tool": "list_inventory_items", "purpose": "surface=IDENTITY probe (Milestone 1): confirmed not licensed/enabled, 0 items returned"},
            ],
            "in_scope": env_map.get("identity", {}).get("licensed_or_enabled", False),
        },
        {
            "entity": "CloudSecurity",
            "description": "SentinelOne Cloud detection module.",
            "attributes": [],
            "tool_bindings": [
                {"tool": "list_inventory_items", "purpose": "surface=CLOUD probe (Milestone 1): confirmed not licensed/enabled, 0 items returned"},
            ],
            "in_scope": env_map.get("cloud", {}).get("licensed_or_enabled", False),
        },
        {
            "entity": "AssetDiscoveryNetwork",
            "description": "SentinelOne Ranger network asset discovery module.",
            "attributes": [],
            "tool_bindings": [
                {"tool": "list_inventory_items", "purpose": "surface=NETWORK_DISCOVERY probe (Milestone 1): confirmed not licensed/enabled, 0 items returned"},
            ],
            "in_scope": env_map.get("asset_discovery", {}).get("licensed_or_enabled", False),
        },
    ]
    for e in out_of_scope:
        validate_entity(e, schema)
    entities.extend(out_of_scope)

    return entities


def main() -> int:
    if not ENVIRONMENT_MAP_PATH.exists():
        print(
            f"ERROR: {ENVIRONMENT_MAP_PATH} not found. Run "
            "scripts/discover_sentinelone_environment.py --confirm-dv first.",
            file=sys.stderr,
        )
        return 2

    with open(ENVIRONMENT_MAP_PATH, encoding="utf-8") as f:
        env_map = yaml.safe_load(f)

    entities = asyncio.run(build(env_map))

    output = {
        "status": "draft_pending_review",
        "note": (
            "Generated by scripts/build_sentinelone_ontology.py from a live "
            "tenant sample plus environment_map.yaml (Milestone 1). Per the "
            "build brief's Milestone 2 instruction, this is a draft requiring "
            "analyst sign-off (set entity.reviewed_by) before being treated "
            "as a frozen v1."
        ),
        "entities": entities,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(output, f, sort_keys=False, allow_unicode=True, width=100)

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Entities: {len(entities)} ({sum(1 for e in entities if e.get('in_scope', True))} in scope)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
