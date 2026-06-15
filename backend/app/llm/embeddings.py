from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# ── Lazy model singleton ───────────────────────────────────────────────────────
# Model is downloaded once (~90 MB) on first use and kept in memory.
# all-MiniLM-L6-v2: fast, small, excellent semantic similarity quality.

_MODEL: "SentenceTransformer | None" = None
_LOCK = threading.Lock()
_MODEL_NAME = "all-MiniLM-L6-v2"


def _load_model() -> "SentenceTransformer":
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _LOCK:
        if _MODEL is None:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer(_MODEL_NAME)
    return _MODEL


def warmup() -> None:
    """
    Pre-load the model in a background thread so the first user request
    doesn't pay the ~2-second load cost.
    """
    t = threading.Thread(target=_load_model, daemon=True)
    t.start()


def get_embeddings(texts: list[str]) -> np.ndarray:
    """
    Encode a list of texts into L2-normalised embedding vectors.
    Returns an (N, D) numpy float32 array.
    Raises RuntimeError if the model cannot be loaded.
    """
    model = _load_model()
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,   # L2 normalise → dot product = cosine sim
        convert_to_numpy=True,
    )
    return embeddings.astype(np.float32)


def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    """
    Given L2-normalised embeddings (N, D), return the (N, N) cosine
    similarity matrix. Since embeddings are already normalised,
    this is just the dot product.
    """
    return embeddings @ embeddings.T
