import httpx
import json
import numpy as np
import pytest

from app.core.config import settings
from app.rag import embeddings


def configure(monkeypatch, provider, api_key="test-key"):
    monkeypatch.setenv("EMBEDDING_PROVIDER", provider)
    monkeypatch.setenv("EMBEDDING_API_KEY", api_key)
    settings.cache_clear()
    embeddings._query_bytes.cache_clear()


def mock_http(monkeypatch, handler):
    original_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        embeddings.httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )


def vector(value=1.0, dimension=384):
    result = [0.0] * dimension
    result[0] = value
    return result


@pytest.mark.parametrize("provider", ["gemini", "openai_compatible", "huggingface"])
def test_http_embedding_providers_return_normalized_vectors(monkeypatch, provider):
    configure(monkeypatch, provider)
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append((request, body))
        if provider == "gemini":
            payload = {"embeddings": [{"values": vector()}, {"values": vector(2)}]}
        elif provider == "openai_compatible":
            payload = {
                "data": [
                    {"index": 1, "embedding": vector(2)},
                    {"index": 0, "embedding": vector()},
                ]
            }
        else:
            token_vectors = [
                [vector(), [0.0] * 383 + [1.0]],
                [vector(2), [0.0] * 383 + [4.0]],
            ]
            payload = token_vectors
        return httpx.Response(200, json=payload)

    mock_http(monkeypatch, handle)
    results = embeddings.encode(["first", "second"])

    assert len(results) == 2
    assert all(result.shape == (384,) for result in results)
    assert all(np.linalg.norm(result) == pytest.approx(1.0) for result in results)
    request, body = requests[0]
    if provider == "gemini":
        assert request.url.path.endswith("/models/gemini-embedding-001:batchEmbedContents")
        assert request.headers["x-goog-api-key"] == "test-key"
        assert body["requests"][0]["outputDimensionality"] == 384
    elif provider == "openai_compatible":
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["dimensions"] == 384
        assert body["input"] == ["first", "second"]
    else:
        assert request.url.path.endswith(
            "/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction"
        )
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["inputs"] == ["first", "second"]
        assert results[0][0] == pytest.approx(2 ** -0.5)
        assert results[0][-1] == pytest.approx(2 ** -0.5)


def test_http_requests_are_batched_at_most_32(monkeypatch):
    configure(monkeypatch, "openai_compatible")
    batch_sizes = []

    def handle(request):
        body = json.loads(request.content)
        batch_sizes.append(len(body["input"]))
        return httpx.Response(
            200,
            json={"data": [{"embedding": vector()} for _ in body["input"]]},
        )

    mock_http(monkeypatch, handle)
    assert len(embeddings.encode(["text"] * 33)) == 33
    assert batch_sizes == [32, 1]


def test_remote_embedding_dimension_is_validated(monkeypatch):
    configure(monkeypatch, "openai_compatible")
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": [{"embedding": vector(dimension=383)}]}
        ),
    )

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        embeddings.encode(["short vector"])


@pytest.mark.parametrize("failure", ["http_429", "missing_key"])
def test_retriever_falls_back_to_lexical_results(monkeypatch, failure):
    api_key = "" if failure == "missing_key" else "test-key"
    configure(monkeypatch, "openai_compatible", api_key)
    if failure == "http_429":
        mock_http(monkeypatch, lambda request: httpx.Response(429))

    from app.rag import retrieval

    evidence = retrieval.Evidence(
        chunk_id=1,
        title="Arbor Dubai courtyard gardens",
        source="darglobal",
        url="https://example.test/arbor",
        text="Arbor Dubai courtyard gardens include landscaped outdoor spaces.",
        fetched_at="2026-01-01",
        score=1.0,
    )
    monkeypatch.setattr(retrieval, "lexical_search", lambda *args, **kwargs: [evidence])
    monkeypatch.setattr(retrieval, "structured_search", lambda *args, **kwargs: [])

    def semantic(*args, **kwargs):
        embeddings.query_embedding("Arbor Dubai courtyard gardens")
        return []

    monkeypatch.setattr(retrieval, "semantic_search", semantic)
    results, degraded = retrieval.HybridRetriever().retrieve(
        "Arbor Dubai courtyard gardens", ["darglobal"]
    )

    assert [item.chunk_id for item in results] == [1]
    assert degraded == ["semantic"]


def test_indexer_reports_unconfigured_remote_provider(monkeypatch):
    configure(monkeypatch, "gemini", "")
    from app.rag.indexer import index_missing_vectors

    assert index_missing_vectors() == {
        "indexed": 0,
        "status": "degraded",
        "reason": "embedding_api_unconfigured",
    }
