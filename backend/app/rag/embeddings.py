"""Local and HTTP embedding providers with bounded concurrency and query caching."""
from functools import lru_cache
from threading import RLock

import httpx
import numpy as np

from app.core.config import settings

_inference_lock = RLock()
_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_PROVIDER_MODELS = {
    "gemini": "gemini-embedding-001",
    "openai_compatible": "text-embedding-3-small",
    "huggingface": "sentence-transformers/all-MiniLM-L6-v2",
}


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


def provider_model_name(provider: str, configured_model: str) -> str:
    if configured_model != _LOCAL_MODEL:
        return configured_model
    return _PROVIDER_MODELS.get(provider, configured_model)


def _normalize(vector, dimension: int) -> np.ndarray:
    try:
        result = np.asarray(vector, dtype=np.float32).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Embedding provider returned an invalid vector") from exc
    if result.size != dimension:
        raise RuntimeError(
            f"Embedding dimension mismatch: expected {dimension}, received {result.size}"
        )
    norm = float(np.linalg.norm(result))
    if not np.isfinite(norm) or norm == 0:
        raise RuntimeError("Embedding provider returned a zero or non-finite vector")
    return result / norm


def _http_json(provider: str, url: str, api_key: str, payload: dict, *, gemini: bool = False):
    headers = {"Content-Type": "application/json"}
    headers["x-goog-api-key" if gemini else "Authorization"] = (
        api_key if gemini else f"Bearer {api_key}"
    )
    try:
        with httpx.Client(timeout=45) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status is not None else type(exc).__name__
        raise RuntimeError(f"{provider} embedding API request failed ({detail})") from exc


def _pool_huggingface_output(output, batch_size: int) -> list:
    if not isinstance(output, list) or not output:
        raise RuntimeError("Hugging Face embedding API returned an invalid response")
    if batch_size == 1:
        samples = [output]
    elif len(output) == batch_size:
        samples = output
    else:
        raise RuntimeError(
            f"Hugging Face embedding API returned {len(output)} vectors for {batch_size} inputs"
        )

    pooled = []
    for sample in samples:
        values = np.asarray(sample, dtype=np.float32)
        if values.ndim == 3 and values.shape[0] == 1:
            values = values[0]
        if values.ndim == 2:
            values = values.mean(axis=0)
        if values.ndim != 1:
            raise RuntimeError("Hugging Face embedding API returned an invalid vector shape")
        pooled.append(values)
    return pooled


def _remote_batch(texts: list[str], provider: str, model_name: str, dimension: int) -> list[np.ndarray]:
    cfg = settings()
    if not cfg.embedding_api_key:
        raise RuntimeError(
            f"EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER={provider}"
        )

    if provider == "gemini":
        url = cfg.embedding_api_url or (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:batchEmbedContents"
        )
        payload = {
            "requests": [
                {
                    "model": f"models/{model_name}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": dimension,
                }
                for text in texts
            ]
        }
        response = _http_json(provider, url, cfg.embedding_api_key, payload, gemini=True)
        if not isinstance(response, dict):
            raise RuntimeError("Gemini embedding API returned an invalid response")
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Gemini embedding API returned an invalid response")
        vectors = [item.get("values") for item in embeddings]
    elif provider == "openai_compatible":
        url = cfg.embedding_api_url or "https://api.jina.ai/v1/embeddings"
        payload = {"model": model_name, "input": texts, "dimensions": dimension}
        response = _http_json(provider, url, cfg.embedding_api_key, payload)
        if not isinstance(response, dict):
            raise RuntimeError("OpenAI-compatible embedding API returned an invalid response")
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise RuntimeError("OpenAI-compatible embedding API returned an invalid response")
        if all(isinstance(item, dict) and "index" in item for item in data):
            data = sorted(data, key=lambda item: item["index"])
        vectors = [item.get("embedding") if isinstance(item, dict) else None for item in data]
    elif provider == "huggingface":
        url = cfg.embedding_api_url or (
            f"https://router.huggingface.co/hf-inference/models/{model_name}/pipeline/feature-extraction"
        )
        response = _http_json(
            provider, url, cfg.embedding_api_key, {"inputs": texts}
        )
        vectors = _pool_huggingface_output(response, len(texts))
    else:
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    return [_normalize(vector, dimension) for vector in vectors]


def encode(texts: list[str]) -> list[np.ndarray]:
    if not texts:
        return []
    cfg = settings()
    with _inference_lock:
        if cfg.embedding_provider == "local":
            outputs = model().encode(
                texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False
            )
            vectors = [np.asarray(vector, dtype=np.float32) for vector in outputs]
        else:
            model_name = provider_model_name(cfg.embedding_provider, cfg.embedding_model)
            vectors = []
            for start in range(0, len(texts), 32):
                vectors.extend(
                    _remote_batch(texts[start:start + 32], cfg.embedding_provider, model_name,
                                  cfg.embedding_dim)
                )
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding provider returned an invalid number of vectors")
    for vector in vectors:
        if vector.size != cfg.embedding_dim:
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {cfg.embedding_dim}, received {vector.size}"
            )
    return vectors


@lru_cache(maxsize=256)
def _query_bytes(provider: str, api_url: str, model_name: str, dimension: int, query: str) -> bytes:
    vector = encode([query])[0]
    if len(vector) != dimension:
        raise RuntimeError("Embedding dimension mismatch")
    return serialize(vector)


def query_embedding(query: str) -> bytes:
    cfg = settings()
    if cfg.embedding_provider != "local" and not cfg.embedding_api_key:
        raise RuntimeError(
            f"EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER={cfg.embedding_provider}"
        )
    # Cache embeddings, never retrieval results or answers. Index changes remain visible.
    with _inference_lock:
        return _query_bytes(
            cfg.embedding_provider, cfg.embedding_api_url,
            provider_model_name(cfg.embedding_provider, cfg.embedding_model),
            cfg.embedding_dim, query,
        )


def serialize(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()
