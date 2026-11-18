"""CPU embeddings with bounded concurrency and exact-query vector caching."""
from functools import lru_cache
from threading import RLock
import numpy as np
from app.core.config import settings

_inference_lock = RLock()


@lru_cache(maxsize=1)
def _load_model(name: str, threads: int):
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(threads)
    return SentenceTransformer(name, device="cpu")


def model():
    cfg = settings()
    with _inference_lock:
        return _load_model(cfg.embedding_model, cfg.embedding_cpu_threads)


def encode(texts: list[str]) -> list[np.ndarray]:
    if not texts:
        return []
    with _inference_lock:
        outputs = model().encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
    return [np.asarray(v, dtype=np.float32) for v in outputs]


@lru_cache(maxsize=256)
def _query_bytes(model_name: str, dimension: int, query: str) -> bytes:
    vector = encode([query])[0]
    if len(vector) != dimension:
        raise RuntimeError("Embedding dimension mismatch")
    return serialize(vector)


def query_embedding(query: str) -> bytes:
    cfg = settings()
    # Cache embeddings, never retrieval results or answers. Index changes remain visible.
    with _inference_lock:
        return _query_bytes(cfg.embedding_model, cfg.embedding_dim, query)


def serialize(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()
