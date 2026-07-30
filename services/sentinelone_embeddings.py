"""Local embedding model for the SentinelOne router and retrieval store.

Phase 2, Milestone 6. Uses fastembed (ONNX runtime, no torch dependency) so
the routing decision stays on this infrastructure -- no external embedding
API call, per the build brief's explicit requirement. The model is loaded
once per process and reused; embedding ~40 short strings takes well under a
second after the one-time model load.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

import numpy as np

logger = logging.getLogger(__name__)

# BAAI/bge-base-en-v1.5 via fastembed: 768-dim, ONNX-quantized, ~500MB.
# The smaller bge-small-en-v1.5 (384-dim) was tried first but measurably
# under-separates short security questions: unrelated probes like "what is
# the weather forecast for tomorrow" scored 0.69 cosine against
# "how many alerts this week" -- above any usable confidence threshold,
# purely from generic short-sentence structure, not topical overlap. Recorded
# during Milestone 6 validation (scripts/validate_sentinelone_router.py);
# bge-base-en-v1.5 pushes the same distractor down to ~0.61 while keeping
# real gap-closing paraphrases at 0.63-1.0, which is what
# ROUTER_CONFIDENCE_THRESHOLD in sentinelone_router_service.py is calibrated
# against.
SENTINELONE_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
SENTINELONE_EMBEDDING_DIM = 768


@lru_cache(maxsize=1)
def _get_model():
    from fastembed import TextEmbedding

    logger.info("Loading local embedding model %s", SENTINELONE_EMBEDDING_MODEL)
    return TextEmbedding(model_name=SENTINELONE_EMBEDDING_MODEL)


def embed_texts(texts: Sequence[str]) -> np.ndarray:
    """Embed a batch of strings. Returns an (n, SENTINELONE_EMBEDDING_DIM) array."""
    if not texts:
        return np.zeros((0, SENTINELONE_EMBEDDING_DIM), dtype=np.float32)
    model = _get_model()
    return np.array(list(model.embed(list(texts))), dtype=np.float32)


def embed_one(text: str) -> np.ndarray:
    """Embed a single string. Returns a (SENTINELONE_EMBEDDING_DIM,) array."""
    return embed_texts([text])[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def cosine_similarity_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one query vector against every row of `matrix`."""
    if matrix.shape[0] == 0:
        return np.zeros((0,), dtype=np.float32)
    query_norm = np.linalg.norm(query)
    matrix_norms = np.linalg.norm(matrix, axis=1)
    denom = query_norm * matrix_norms
    denom[denom == 0] = 1e-12
    return (matrix @ query) / denom
