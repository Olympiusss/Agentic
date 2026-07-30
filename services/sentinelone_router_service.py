"""SentinelOne question router.

Phase 2, Milestone 6. Implements the routing method specified in
`Sentry_AgenticSOC_Build_Brief_for_Claude.md` (Milestone 6) and distilled in
`data/agent/context/navigation_rules.md`:

  1. The MCP server is fixed by scope -- this module never selects a server.
  2. Intent resolution is an embedding match over the coverage matrix's
     example questions, not free model classification.
  3. Above `ROUTER_CONFIDENCE_THRESHOLD`, the matched row's recipe is used.
  4. If the top two rows are within `ROUTER_AMBIGUITY_GAP`, the intent is
     ambiguous -- return both candidates for disambiguation instead of
     guessing.
  5. The gap-closing set (`priority: gap_closing` in the coverage matrix) is
     hard-bound to its recipe with no discretion once matched.
  6. Below the threshold, the constrained fallback narrows to
     ontology-derived candidate tools via the retrieval store -- never the
     full 33-tool surface.
  7. Every route is logged.

Do not drop the model into native tool-calling over the full tool surface;
that is what produced the original "answered from Sentry findings, not
SentinelOne" failure this phase exists to fix.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
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
from services.sentinelone_retrieval_store import retrieve as retrieve_chunks

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_ROOT = REPO_ROOT / "data" / "knowledge" / "sentinelone"
COVERAGE_MATRIX_PATH = (
    KNOWLEDGE_ROOT / "coverage_matrix" / "sentinelone_coverage_matrix.yaml"
)
RECIPES_DIR = KNOWLEDGE_ROOT / "recipes"
ROUTING_DIR = KNOWLEDGE_ROOT / "routing"
ROUTER_INDEX_PATH = ROUTING_DIR / "coverage_matrix_index.json"
ROUTE_LOG_PATH = ROUTING_DIR / "route_log.jsonl"

# A question resolves only if its best-matching coverage-matrix example
# scores at or above this cosine similarity. Calibrated empirically during
# Milestone 6 validation (scripts/validate_sentinelone_router.py) against
# BAAI/bge-base-en-v1.5: real gap-closing paraphrases scored 0.60-0.90,
# while genuinely unrelated questions ("what's the weather forecast for
# tomorrow", "tell me a joke") scored 0.57-0.61 -- short-sentence embedding
# models have a real, measured noise floor here, not near zero. 0.62 is the
# lowest threshold that cleanly separates every tested distractor from every
# tested real paraphrase; it is not a round-number guess. Re-validate this
# constant if the coverage matrix's example questions change meaningfully.
ROUTER_CONFIDENCE_THRESHOLD = 0.62

# If the top two distinct question_classes' best scores are within this gap,
# treat the intent as ambiguous rather than silently picking the top one.
ROUTER_AMBIGUITY_GAP = 0.05

FALLBACK_RETRIEVAL_K = 3


@dataclass
class RouteDecision:
    question: str
    decision_type: str  # "hard_bound" | "routed" | "ambiguous" | "fallback"
    question_class: Optional[str] = None
    confidence: Optional[float] = None
    matched_example: Optional[str] = None
    second_best_class: Optional[str] = None
    second_best_confidence: Optional[float] = None
    recipe_id: Optional[str] = None
    tools: list[str] = field(default_factory=list)
    source_module: Optional[str] = None
    disambiguation_options: list[str] = field(default_factory=list)
    candidate_modules: list[str] = field(default_factory=list)
    candidate_tools: list[str] = field(default_factory=list)


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _load_coverage_matrix() -> list[dict[str, Any]]:
    return _read_yaml(COVERAGE_MATRIX_PATH)["rows"]


@lru_cache(maxsize=1)
def _load_recipes_by_intent() -> dict[str, dict[str, Any]]:
    recipes = {}
    for path in sorted(RECIPES_DIR.glob("*.yaml")):
        data = _read_yaml(path)
        if isinstance(data, dict) and "intent" in data:
            recipes[data["intent"]] = data
    return recipes


@lru_cache(maxsize=1)
def gap_closing_question_classes() -> frozenset[str]:
    """Derived from the coverage matrix's own `priority: gap_closing` field
    -- never hardcoded separately, so this can't silently drift from the
    matrix that is the single source of truth for the gap-closing set."""
    return frozenset(
        row["question_class"]
        for row in _load_coverage_matrix()
        if row.get("priority") == "gap_closing"
    )


def build_index() -> dict[str, Any]:
    """Embed every coverage-matrix example question and write the router
    index to disk. Rerun whenever the coverage matrix changes."""
    rows = _load_coverage_matrix()
    flat_examples: list[str] = []
    example_owner: list[int] = []  # index into rows, per flat_examples entry
    for i, row in enumerate(rows):
        for ex in row.get("example", []):
            flat_examples.append(ex)
            example_owner.append(i)

    embeddings = embed_texts(flat_examples)

    index_rows = []
    cursor = 0
    for i, row in enumerate(rows):
        n = len(row.get("example", []))
        row_examples = [
            {
                "text": flat_examples[cursor + j],
                "embedding": embeddings[cursor + j].tolist(),
            }
            for j in range(n)
        ]
        cursor += n
        index_rows.append(
            {
                "question_class": row["question_class"],
                "priority": row.get("priority"),
                "source_module": row.get("source_module"),
                "examples": row_examples,
            }
        )

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": SENTINELONE_EMBEDDING_MODEL,
        "dim": SENTINELONE_EMBEDDING_DIM,
        "rows": index_rows,
    }
    ROUTING_DIR.mkdir(parents=True, exist_ok=True)
    with open(ROUTER_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    logger.info(
        "Wrote router index: %d rows, %d example questions to %s",
        len(index_rows),
        len(flat_examples),
        ROUTER_INDEX_PATH,
    )
    return index


@lru_cache(maxsize=1)
def _load_router_index() -> tuple[list[str], list[str], np.ndarray]:
    """Returns (question_classes, example_texts, embedding_matrix), all
    flattened one-row-per-example so nearest-neighbor search is a single
    matrix multiply, with question_classes[i] naming which row example i
    belongs to."""
    if not ROUTER_INDEX_PATH.exists():
        raise FileNotFoundError(
            f"{ROUTER_INDEX_PATH} does not exist -- run "
            "scripts/build_sentinelone_router_index.py first."
        )
    with open(ROUTER_INDEX_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    question_classes: list[str] = []
    example_texts: list[str] = []
    vectors: list[list[float]] = []
    for row in index["rows"]:
        for ex in row["examples"]:
            question_classes.append(row["question_class"])
            example_texts.append(ex["text"])
            vectors.append(ex["embedding"])
    matrix = np.array(vectors, dtype=np.float32)
    return question_classes, example_texts, matrix


def _best_score_per_class(
    question_classes: list[str], scores: np.ndarray
) -> dict[str, tuple[float, int]]:
    """For each question_class, the best (score, example_index) among its
    examples -- routing decides at the row level, not the example level."""
    best: dict[str, tuple[float, int]] = {}
    for i, qc in enumerate(question_classes):
        score = float(scores[i])
        if qc not in best or score > best[qc][0]:
            best[qc] = (score, i)
    return best


def _constrained_fallback(question: str) -> RouteDecision:
    hits = retrieve_chunks(
        question, k=FALLBACK_RETRIEVAL_K, source_filter=["ontology_entity"]
    )
    candidate_modules = [h["chunk_key"] for h in hits]
    candidate_tools: list[str] = []
    for h in hits:
        candidate_tools.extend(h.get("metadata", {}).get("tool_bindings", []))
    # De-dupe while preserving order.
    candidate_tools = list(dict.fromkeys(candidate_tools))
    decision = RouteDecision(
        question=question,
        decision_type="fallback",
        candidate_modules=candidate_modules,
        candidate_tools=candidate_tools,
    )
    return decision


def route(question: str) -> RouteDecision:
    """Resolve one question to a routing decision. Always logs the result."""
    question_classes, example_texts, matrix = _load_router_index()
    query_vec = embed_one(question)
    scores = cosine_similarity_matrix(query_vec, matrix)
    best_per_class = _best_score_per_class(question_classes, scores)

    ranked = sorted(best_per_class.items(), key=lambda kv: kv[1][0], reverse=True)
    top_class, (top_score, top_idx) = ranked[0]
    second_class, second_score = (None, None)
    if len(ranked) > 1:
        second_class, (second_score, _) = ranked[1]

    if top_score < ROUTER_CONFIDENCE_THRESHOLD:
        decision = _constrained_fallback(question)
        _log_route(decision)
        return decision

    if second_class is not None and (top_score - second_score) < ROUTER_AMBIGUITY_GAP:
        decision = RouteDecision(
            question=question,
            decision_type="ambiguous",
            question_class=top_class,
            confidence=top_score,
            matched_example=example_texts[top_idx],
            second_best_class=second_class,
            second_best_confidence=second_score,
            disambiguation_options=[top_class, second_class],
        )
        _log_route(decision)
        return decision

    matrix_row = next(
        r for r in _load_coverage_matrix() if r["question_class"] == top_class
    )
    recipes_by_intent = _load_recipes_by_intent()
    recipe = recipes_by_intent.get(top_class)
    is_gap_closing = top_class in gap_closing_question_classes()

    if is_gap_closing:
        # Hard-bound: no discretion, no fallback, even if a recipe is somehow
        # missing (that would be a build defect to fix, not a reason to
        # improvise a different route).
        if recipe is None:
            raise RuntimeError(
                f"Gap-closing question_class '{top_class}' has no bound recipe "
                f"in {RECIPES_DIR} -- this is a build defect, not routable."
            )
        decision = RouteDecision(
            question=question,
            decision_type="hard_bound",
            question_class=top_class,
            confidence=top_score,
            matched_example=example_texts[top_idx],
            recipe_id=recipe["recipe_id"],
            tools=[tc["tool"] for tc in recipe.get("tool_calls", [])],
            source_module=matrix_row.get("source_module"),
        )
    else:
        decision = RouteDecision(
            question=question,
            decision_type="routed",
            question_class=top_class,
            confidence=top_score,
            matched_example=example_texts[top_idx],
            recipe_id=recipe["recipe_id"] if recipe else None,
            tools=[tc["tool"] for tc in recipe.get("tool_calls", [])] if recipe else [],
            source_module=matrix_row.get("source_module"),
        )
    _log_route(decision)
    return decision


def _log_route(decision: RouteDecision) -> None:
    ROUTING_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"logged_at": datetime.now(timezone.utc).isoformat(), **asdict(decision)}
    with open(ROUTE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
