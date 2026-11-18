# RAG architecture and evidence contracts

## Ingestion

Only a permitted source adapter can reach the crawler. The crawler discovers official sitemap URLs and permitted on-site links, checks robots.txt and official host allowlists, extracts headings/paragraphs, persists a document with immutable URL provenance, and generates chunks. Unchanged SHA-256 content skips re-indexing. Changed content replaces its old chunks, and stale vectors are removed by original chunk ID.

## Chunker

`StructureAwareChunker` separates by document sections/headings, then sentence/paragraph boundaries, and falls back to token-boundary windows. Target=400, max=600, overlap=60 (configurable in class); heading metadata remains attached. `tiktoken` is preferred; test-only degraded fallback token counts are lexical. Chunk changes are tracked via checksum. For property JSON-LD, structured values are stored separately and never inferred.

## Retrieval

1. FTS5 ranks exact lexical tokens using `bm25` on heading and body.
2. Local multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) produces 384-dimensional normalized embeddings stored/queryable through `sqlite-vec`.
3. SQL structured retrieval prioritizes verified metadata and applies explicit bedroom/price conditions.
4. Reciprocal rank fusion combines branch rank positions using weights 1.2/1.0/0.8, constant k=60.
5. A conservative multi-term word overlap gate removes generic source-name-only matches. Candidates are ordered by query coverage/title relevance and fused rank, then near-duplicates are suppressed and chunks per URL are capped. This can reduce recall in cross-language or synonym-heavy queries; evaluate on real content before tuning.
6. A pluggable `IdentityReranker` avoids introducing an unmeasured cross-encoder latency cost.

## Sufficient evidence and on-demand discovery

The orchestrator triggers an additional bounded official sitemap discovery when initial retrieval is empty, requested factual fields are missing, the model explicitly abstains, or the query asks for fresh information. URLs are ranked by query-token overlap in the **URL path**, then eligible official HTML is fetched and reindexed. Wasalt discovery is never attempted without documented authorization. Failure leads to abstention, not an invented answer.

## Grounding

The LLM receives the current question, a bounded conversation context when necessary, and an evidence packet containing source identifiers, document titles, observation dates and bounded excerpts. Prior assistant messages are never treated as source evidence. Web content is explicitly untrusted. The generator must reference `[E1]` etc; server-side citation validation checks IDs and rejects unsupported numeric tokens against the excerpts actually cited, rather than a different retrieved document. The platform stores and returns citation URLs from SQLite, never model-supplied external URLs. Invalid output triggers bounded free-model fallbacks then a specific, visibly non-generated failure message. Dedicated no-evidence/insufficient-evidence responses are distinct from provider failures. Qualitative claim verification remains a known evaluation limitation; no system can guarantee absence of hallucination from prompting alone.

## Streaming

SSE events: `activity` (actual phase), `delta` (verified response fragments), `done` (metadata/citations), `error` (failure). The server buffers the upstream LLM completion until citation validation succeeds before streaming text. Unverified provider tokens are never exposed to browser users.

## Evaluation

`make eval` uses a file `evaluations/retrieval/queries.jsonl` in which each line specifies `question` and `relevant_urls` for **actual sourced records**. It refuses to invent evaluation questions/labels if no such dataset exists. Target metrics: Recall@5 and citations/abstention accuracy. Cross-encoder and embedding model changes require benchmark comparison. The repository contains no fabricated benchmark report.
