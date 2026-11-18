# Component architecture

```mermaid
flowchart LR
  UI[Next.js Frontend] --> API[FastAPI v1]
  API --> RAG[Evidence-first Orchestrator]
  RAG --> FTS[SQLite FTS5]
  RAG --> VEC[sqlite-vec]
  RAG --> META[Property SQL]
  RAG --> TOOL[Official-source bounded lookup]
  TOOL --> P[Policy + Crawl]
  P --> DB[(SQLite volume)]
  FTS --> DB
  VEC --> DB
  META --> DB
  RAG --> OR[OpenRouter Model Registry + Gateway]
  OR --> CV[Citation + Numeric Guard]
  CV --> UI
  WORKER[Ingestion Worker] --> P
  INIT[Migrations + Bootstrap] --> DB
```

Trust boundaries:

- Browser: public data only, no API keys.
- API: validates requests, sources, model IDs and conversation tokens.
- Tool worker: official host allowlist and permission checks before network access.
- Retrieved content: untrusted evidence only.
- Model response: untrusted until citation and numeric checks pass.
- SQLite: persistent on single host, no public database port.

Operational notes:

- Data ingestion and query-triggered lookup reuse the same document upsert path.
- Vector model loads lazily; missing model results in explicit degraded retrieval.
- Provider selection is dynamically read from OpenRouter catalog rather than a stale static model list.
- API returns SSE events to display verified text and actual search phases.
