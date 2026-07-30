"""Build the Milestone 6 embedding indexes: the coverage-matrix router index
and the knowledge retrieval-store chunk index.

Both are local, file-based artifacts (see services/sentinelone_router_service.py
and services/sentinelone_retrieval_store.py for why: this tenant's Postgres
does not actually have pgvector installed, and the brief itself asks for
model-agnostic YAML/JSON artifacts). Rerun this whenever the coverage matrix,
ontology, dv_cookbook, recipes, or data/agent/tools content changes.

Usage:
    python scripts/build_sentinelone_router_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services import sentinelone_retrieval_store  # noqa: E402
from services import sentinelone_router_service  # noqa: E402


def main() -> None:
    print("Building coverage-matrix router index...")
    router_index = sentinelone_router_service.build_index()
    n_examples = sum(len(r["examples"]) for r in router_index["rows"])
    print(f"  {len(router_index['rows'])} rows, {n_examples} example questions")
    print(f"  -> {sentinelone_router_service.ROUTER_INDEX_PATH}")

    print("Building knowledge retrieval-store chunk index...")
    store_index = sentinelone_retrieval_store.build_index()
    by_source: dict[str, int] = {}
    for c in store_index["chunks"]:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    for source, count in sorted(by_source.items()):
        print(f"  {source}: {count}")
    print(f"  -> {sentinelone_retrieval_store.INDEX_PATH}")


if __name__ == "__main__":
    main()
