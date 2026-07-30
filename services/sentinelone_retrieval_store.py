"""Chunked retrieval store over the SentinelOne knowledge artifacts.

Phase 2, Milestone 6. Loads the ontology, coverage matrix, Deep Visibility
cookbook, recipe library, and enriched tool descriptions into short,
independently-retrievable chunks, embeds each with the local model in
`services/sentinelone_embeddings.py`, and answers `retrieve(query, k)` with
the nearest chunks by cosine similarity.

Two consumers:
  - The router's constrained fallback (`services/sentinelone_router_service.py`),
    which retrieves the nearest `ontology_entity` chunks to narrow the tool
    surface when nothing clears the confidence threshold.
  - Anything else that needs a specific fact chunk (a DV template, a field
    dictionary category, a recipe) without loading every knowledge file.

Everything here is read-only and file-based -- no database dependency (this
tenant's Postgres does not actually have the pgvector extension installed
despite CLAUDE.md's architecture note; see the Milestone 6 PR description).
The index is a plain JSON file, consistent with every other knowledge
artifact in this phase being YAML/markdown and model-agnostic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

from services.sentinelone_embeddings import (
    SENTINELONE_EMBEDDING_DIM,
    SENTINELONE_EMBEDDING_MODEL,
    cosine_similarity_matrix,
    embed_one,
    embed_texts,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_ROOT = REPO_ROOT / "data" / "knowledge" / "sentinelone"
AGENT_ROOT = REPO_ROOT / "data" / "agent"
STORE_DIR = KNOWLEDGE_ROOT / "retrieval_store"
INDEX_PATH = STORE_DIR / "chunks_index.json"


@dataclass
class Chunk:
    chunk_id: str
    source: str
    chunk_key: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ontology_chunks() -> list[Chunk]:
    data = _read_yaml(KNOWLEDGE_ROOT / "ontology" / "sentinelone_ontology.yaml")
    chunks = []
    for entity in data.get("entities", []):
        name = entity["entity"]
        in_scope = entity.get("in_scope", False)
        tool_bindings = entity.get("tool_bindings", [])
        tools_text = ", ".join(f"{t['tool']} ({t['purpose']})" for t in tool_bindings)
        text = (
            f"Entity: {name}. In scope: {in_scope}. {entity.get('description', '')} "
            f"Tool bindings: {tools_text or 'none'}."
        )
        chunks.append(
            Chunk(
                chunk_id=f"ontology_entity:{name}",
                source="ontology_entity",
                chunk_key=name,
                text=text,
                metadata={
                    "in_scope": in_scope,
                    "tool_bindings": [t["tool"] for t in tool_bindings],
                },
            )
        )
    return chunks


def _coverage_matrix_chunks() -> list[Chunk]:
    data = _read_yaml(
        KNOWLEDGE_ROOT / "coverage_matrix" / "sentinelone_coverage_matrix.yaml"
    )
    chunks = []
    for row in data.get("rows", []):
        qc = row["question_class"]
        examples = "; ".join(row.get("example", []))
        text = (
            f"Question class: {qc}. Example questions: {examples}. "
            f"Source module: {row.get('source_module', '')}. "
            f"Retrieval path: {row.get('retrieval_path', '')}."
        )
        chunks.append(
            Chunk(
                chunk_id=f"coverage_matrix_row:{qc}",
                source="coverage_matrix_row",
                chunk_key=qc,
                text=text,
                metadata={
                    "priority": row.get("priority"),
                    "status": row.get("status"),
                    "source_module": row.get("source_module"),
                },
            )
        )
    return chunks


def _field_dictionary_chunks() -> list[Chunk]:
    data = _read_yaml(KNOWLEDGE_ROOT / "dv_cookbook" / "field_dictionary.yaml")
    chunks = []
    for cat in data.get("categories", []):
        name = cat["category"]
        fields = ", ".join(cat.get("fields_confirmed", [])) or "none confirmed"
        text = (
            f"Deep Visibility field dictionary, category: {name}. "
            f"Confirmed fields: {fields}. Status: {cat.get('status')}."
        )
        chunks.append(
            Chunk(
                chunk_id=f"dv_field_dictionary:{name}",
                source="dv_field_dictionary",
                chunk_key=name,
                text=text,
                metadata={"status": cat.get("status")},
            )
        )
    return chunks


def _dv_hunt_template_chunks() -> list[Chunk]:
    chunks = []
    for path in sorted((KNOWLEDGE_ROOT / "dv_cookbook").glob("*.yaml")):
        if path.name == "field_dictionary.yaml":
            continue
        data = _read_yaml(path)
        if not isinstance(data, dict) or "template_id" not in data:
            continue
        tid = data["template_id"]
        mitre = data.get("mitre", [])
        mitre_text = "; ".join(
            f"{m.get('tactic')} / {m.get('technique_id')} {m.get('technique_name')}"
            for m in mitre
        )
        query = data.get("query_source", {}).get("resulting_query", "")
        pattern = data.get("hunt_pattern")
        text = (
            f"Deep Visibility hunt template: {tid}. Pattern: {pattern}. "
            f"MITRE: {mitre_text}. Query: {query}. Status: {data.get('status')}."
        )
        chunks.append(
            Chunk(
                chunk_id=f"dv_hunt_template:{tid}",
                source="dv_hunt_template",
                chunk_key=tid,
                text=text,
                metadata={
                    "status": data.get("status"),
                    "hunt_pattern": data.get("hunt_pattern"),
                },
            )
        )
    return chunks


def _recipe_chunks() -> list[Chunk]:
    chunks = []
    for path in sorted((KNOWLEDGE_ROOT / "recipes").glob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict) or "recipe_id" not in data:
            continue
        rid = data["recipe_id"]
        tools = ", ".join(tc.get("tool", "") for tc in data.get("tool_calls", []))
        text = (
            f"Recipe: {rid}. Intent: {data.get('intent')}. Tool calls: {tools}. "
            f"Expected result shape: {data.get('expected_result_shape', '')}. "
            f"Status: {data.get('status')}."
        )
        chunks.append(
            Chunk(
                chunk_id=f"recipe:{rid}",
                source="recipe",
                chunk_key=rid,
                text=text,
                metadata={"intent": data.get("intent"), "status": data.get("status")},
            )
        )
    return chunks


def _agent_tool_chunks() -> list[Chunk]:
    chunks = []
    for path in sorted((AGENT_ROOT / "tools").glob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        server = data.get("mcp_server", "unknown")
        for tool in data.get("tools", []):
            name = tool["tool"]
            when = "; ".join(tool.get("when_to_use", []) or [])
            not_when = "; ".join(tool.get("when_not_to_use", []) or [])
            differs = "; ".join(
                f"vs {k}: {v}" for k, v in (tool.get("differs_from") or {}).items()
            )
            text = (
                f"Tool: {name} (server: {server}). When to use: {when}. "
                f"When not to use: {not_when}. Differs from: {differs}."
            )
            chunks.append(
                Chunk(
                    chunk_id=f"agent_tool:{server}:{name}",
                    source="agent_tool",
                    chunk_key=name,
                    text=text,
                    metadata={"mcp_server": server},
                )
            )
    return chunks


def collect_all_chunks() -> list[Chunk]:
    """Every chunk this store indexes, from real, already-committed artifacts."""
    return (
        _ontology_chunks()
        + _coverage_matrix_chunks()
        + _field_dictionary_chunks()
        + _dv_hunt_template_chunks()
        + _recipe_chunks()
        + _agent_tool_chunks()
    )


def build_index() -> dict[str, Any]:
    """Embed every chunk and write the index to disk. Returns the index dict."""
    chunks = collect_all_chunks()
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": SENTINELONE_EMBEDDING_MODEL,
        "dim": SENTINELONE_EMBEDDING_DIM,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "source": c.source,
                "chunk_key": c.chunk_key,
                "text": c.text,
                "metadata": c.metadata,
                "embedding": embeddings[i].tolist(),
            }
            for i, c in enumerate(chunks)
        ],
    }
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    logger.info("Wrote %d chunks to %s", len(chunks), INDEX_PATH)
    return index


@lru_cache(maxsize=1)
def _load_index() -> tuple[list[dict[str, Any]], np.ndarray]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"{INDEX_PATH} does not exist -- run "
            "scripts/build_sentinelone_router_index.py first."
        )
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    chunks = index["chunks"]
    matrix = np.array([c["embedding"] for c in chunks], dtype=np.float32)
    return chunks, matrix


def retrieve(
    query: str, k: int = 5, source_filter: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    """Return the top-k chunks by cosine similarity to `query`.

    `source_filter`, if given, restricts to chunks whose `source` is in the
    list (e.g. ["ontology_entity"] for the router's constrained fallback).
    """
    chunks, matrix = _load_index()
    if source_filter:
        keep = [i for i, c in enumerate(chunks) if c["source"] in source_filter]
        if not keep:
            return []
        chunks = [chunks[i] for i in keep]
        matrix = matrix[keep]
    query_vec = embed_one(query)
    scores = cosine_similarity_matrix(query_vec, matrix)
    order = np.argsort(-scores)[:k]
    return [{**chunks[i], "score": float(scores[i]), "embedding": None} for i in order]
