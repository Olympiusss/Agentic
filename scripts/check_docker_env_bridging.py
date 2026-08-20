#!/usr/bin/env python3
"""Catch the "real credential exists but was never bridged into Docker"
bug class before it causes a live incident.

Confirmed, live-verified, and hit **four separate times** in one session
(2026-08-20): a real, working credential existed in the repo-root
``.env`` (SMTP, then SentinelOne, then VirusTotal + AbuseIPDB), but
``docker/docker-compose.yml`` either never referenced the variable at all,
or referenced it only on some services, or referenced it but
``docker/.env`` (what Compose's ``${VAR}`` substitution actually reads at
``docker compose`` invocation time) never had the value copied over --
so the container silently ran with an empty value regardless of the
credential being "configured" from the user's perspective, and the
resulting failure (a capability reporting "not configured", a daemon
never sending an email) looked like a missing-integration bug, not a
deployment bug.

This script does not fix anything -- it reports. Run it after adding any
new credential to the root ``.env``, and before assuming a Docker-side
"not configured" message means the credential itself is missing.

Usage (from repo root)::

    python scripts/check_docker_env_bridging.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_ENV_PATH = REPO_ROOT / ".env"
DOCKER_ENV_PATH = REPO_ROOT / "docker" / ".env"
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yml"

# ${VAR}, ${VAR:-default}, ${VAR-default} -- the three shapes Compose
# actually substitutes. Captures the var name and (if present) whether a
# default was given, since a var with a non-empty literal default (e.g.
# `${DEV_MODE:-false}`) is a deliberate config knob, not a credential gap.
_VAR_REF_RE = re.compile(r"\$\{([A-Z0-9_]+)(:?-)?([^}]*)\}")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser -- good enough for these two files
    (no multi-line values, no export prefixes, optional quoting)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _find_compose_var_refs(path: Path) -> dict[str, list[str]]:
    """Returns {var_name: [default_or_empty, ...]} -- a list because the
    same var can be referenced by multiple services with different (or no)
    defaults; we care about whether ANY reference has no real default."""
    refs: dict[str, list[str]] = {}
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in _VAR_REF_RE.finditer(text):
        var_name = match.group(1)
        default = match.group(3) or ""
        refs.setdefault(var_name, []).append(default)
    return refs


# Compose vars that legitimately have no root-.env equivalent (pure
# deployment knobs, not credentials) -- excluded so the report stays
# focused on the actual bug class this script exists to catch.
_KNOWN_NON_CREDENTIAL_PREFIXES = ("DAEMON_", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB")


def main() -> int:
    root_env = _parse_env_file(ROOT_ENV_PATH)
    docker_env = _parse_env_file(DOCKER_ENV_PATH)
    compose_refs = _find_compose_var_refs(COMPOSE_PATH)

    gaps: list[tuple[str, str]] = []  # (var_name, reason)

    for var_name, defaults in sorted(compose_refs.items()):
        if var_name.startswith(_KNOWN_NON_CREDENTIAL_PREFIXES):
            continue

        root_value = root_env.get(var_name, "")
        docker_value = docker_env.get(var_name, "")

        # The bug this script exists to catch: a real value in the root
        # .env that never made it into docker/.env, so Compose's
        # substitution resolves to empty (or whatever weak default the
        # compose file itself provides) regardless of the "real" value
        # existing somewhere the user set it up correctly.
        if root_value and not docker_value:
            gaps.append((
                var_name,
                f"has a real value in the repo-root .env but is MISSING from docker/.env "
                f"-- every service referencing it will see an empty value",
            ))
            continue

        # A var referenced with no default at all (`${VAR}`, no `:-`) and
        # absent from both files will make `docker compose` itself warn
        # ("variable is not set, defaulting to a blank string") -- worth
        # surfacing distinctly from the "we have it, just not bridged"
        # case above, since the fix differs (need the credential at all,
        # vs. just need to copy it).
        has_bare_ref = any(d == "" for d in defaults)
        if has_bare_ref and not root_value and not docker_value:
            gaps.append((
                var_name,
                "referenced with no default and not present in either .env file "
                "-- if this is meant to be a real credential, it doesn't exist yet anywhere",
            ))

    if not gaps:
        print("No bridging gaps found -- every credential-shaped variable "
              "docker-compose.yml references that has a real root-.env value "
              "is present in docker/.env too.")
        return 0

    print(f"Found {len(gaps)} potential issue(s):\n")
    for var_name, reason in gaps:
        print(f"  {var_name}")
        print(f"    {reason}\n")
    print(
        "Fix: copy the real value from the repo-root .env into docker/.env, "
        "then `docker compose up -d <affected services>` to pick it up "
        "(no rebuild needed for env-only changes)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
