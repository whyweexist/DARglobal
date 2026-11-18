"""Lazy-loaded local multilingual embedding service; never requires paid embedding APIs."""
from functools import lru_cache
import logging
import numpy as np
from app.core.config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings().embedding_model, device="cpu")


def encode(texts: list[str]) -> list[np.ndarray]:
    if not texts:
        return []
    outputs = model().encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
    return [np.asarray(v, dtype=np.float32) for v in outputs]


def serialize(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()
