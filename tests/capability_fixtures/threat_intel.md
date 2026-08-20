# Regression fixture: Threat Intel capability (Milestone 5)

Encodes Milestone 5's acceptance bar: *"Threat Intel enriches a real
indicator with grounded reputation and context, and never presents
inference as fact."*

Real constraint found while building: `cve_search_by_id` returns a full
**CVE Record Format 5.2** document, not a flat `{description, cvss}`
shape — description lives at `containers.cna.descriptions[0].value`,
CVSS lives under `containers.adp[*].metrics[*]`, keyed by whichever
CVSS version the assigner used (`cvssV3_1`, `cvssV3_0`, `cvssV2_0` — no
single fixed key). `capabilities/threat_intel.py`'s `_extract_cve_facts`
parses this defensively.

Hash-reputation (VirusTotal/GTI) is NOT composed — `PURPLEMCP_VT_API_KEY`
confirmed not configured (`data/knowledge/sentinelone/mcp_tools.md`).

## Pass criteria (`tests/unit/test_threat_intel_capability.py`)

1. `_extract_cve_facts` correctly pulls description/CVSS score/severity
   from a realistic CVE Record Format 5.2 fixture.
2. A CVE record missing CVSS metrics entirely doesn't crash — returns
   `None`s, not an exception.
3. `cve_traversal` (asset exposure) is composed via
   `services.sentinelone_recipe_executor.execute()`, never a raw tool.
4. Synthesis failures are caught and returned as `execution_error`.
