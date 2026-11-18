# Tests and evaluation

## Commands

```bash
# Native backend (uses a separate temporary SQLite DB)
cd backend
uv run --extra dev pytest -q

# Run containerized and HTTP checks
make test
make smoke-test

# After JS dependencies are installed
cd frontend
pnpm lint
pnpm build

# Evaluation requires a real labeled source corpus
make eval
```

Tests use isolated **test-only** fabricated strings for parser/SQL mechanics. No test fixture is mounted in production or used to populate the deployed knowledge base. Live website crawling and real OpenRouter inference are not performed in ordinary CI to avoid flaky network, cost, and permission violations.

## RAG evaluation

After authorized ingestion, create `evaluations/retrieval/queries.jsonl` with one line per actual sourced query:

```json
{"question":"A question supported by collected source material","relevant_urls":["https://VALID_OFFICIAL_SOURCE_URL"]}
```

The line above illustrates the format only and should **not** be committed as a claimed evaluated example. Replace with real labeled questions/URLs before executing evaluation. The script refuses to invent benchmarks when data is absent.

Measure Recall@5, citation validity, unsupported-number rejection, correct abstention and source freshness. When changing embeddings or adding reranking, compare results and CPU latency on the same labeled set.

## Important verification limitations

The current test container/image build and Next.js compile require network installations and were not externally executed by the original archive generator. Run them in Codespaces before reporting an assessor-facing production pass. Tests must be rerun after source-specific page selectors are adapted to live authorized pages.
