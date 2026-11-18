# HTTPX-first provider choice and response latency

## Upgrade without deleting data

Preserve `.env` and `data/`, or the existing Docker volume. Update the actual `.env` (not just the example) and restart the API and worker:

```dotenv
WASALT_ENGINE=httpx
APIFY_ENABLED=false
APIFY_LIVE_SEARCH=false
AGENT_MAX_SECONDS=30
LLM_TIMEOUT_SECONDS=30
LLM_TOTAL_SECONDS=60
EMBEDDING_CPU_THREADS=2
SOURCE_ACCESS_COOLDOWN_SECONDS=300
```

Leave `SCRAPER_ENGINE` at your preferred DarGlobal engine (`httpx` or `scrapling`). Keep `RAG_LIVE_SEARCH=true` and your actual Wasalt authorization reference if applicable. `WASALT_ENGINE=inherit` remains supported for backward compatibility. Previously exported environment variables also override defaults. For Docker, settings changes require container recreation; for native mode stop and restart `make local`.

```bash
make local-doctor
make local
# Docker alternative: make up
```

Expected doctor fields include `wasalt_engine: httpx`, `apify_configured: false`, and the configured time limits. This does not establish source reachability. Wasalt may still return HTTP 403 / Cloudflare challenge. The application respects that refusal, does not automatically switch engines, and continues using already stored authorized evidence where appropriate.

## Apify remains optional

If you have authorized use and accept actor charges, keep `WASALT_ENGINE=httpx`, set `APIFY_ENABLED=true`, set `APIFY_TOKEN` in the private environment, leave `APIFY_LIVE_SEARCH=false`, and execute:

```bash
make local-scrape-wasalt ARGS="--engine apify --dry-run --max-pages 10"
make local-scrape-wasalt ARGS="--engine apify --max-pages 40"
make local-index
```

Docker users can use `make scrape-wasalt` with the same arguments. Neither the paid actor nor its optional live-search feature is invoked implicitly when HTTPX is selected. If you specifically want automatic ingestion via Apify, select `WASALT_ENGINE=apify` plus the opt-in/token; separately enable `APIFY_LIVE_SEARCH=true` only if chat-triggered charges are desired. See `docs/apify.md`. Stored documents retrieved by any approved provider are still searchable after switching engines. Free LLM settings are independent of Apify costs.

## Improvements and trade-offs

- All three retrieval branches execute concurrently in a shared bounded thread pool. Results are merged in their previous deterministic branch order. Existing top-K, RRF weights, property constraints, reranker, source filtering, evidence budgets and citation validation are unchanged.
- Structured retrieval resolves the first chunk of each candidate listing in one SQL query, replacing per-listing queries.
- A thread-safe, process-local cache holds up to 256 exact query embeddings per cache, keyed by model, dimension and query. No answers, history, retrieved rows or prices are cached. Query text and vectors remain in process memory until evicted or restart. Document and query model inference use the same loaded CPU model. Embedding CPU threads default to two per process to limit oversubscription; tune this for your VM.
- The default free inference route is tried immediately, without fetching the model catalogue for fallbacks that might never be needed. Explicit model selections still require registry validation. The free catalogue is consulted lazily when a fallback is needed. Free-only validation and the existing three-attempt ceiling are preserved.
- Live discovery no longer sleeps after the final request; delays between actual same-source requests remain in force. A recent explicit direct-access refusal (401/403/429 or Cloudflare challenge) suppresses further chat-triggered direct fetches from that source for five minutes by default. This process-local cooldown is not shared with the scheduled worker; CLI ingestion remains independent and checks policy as before. Set the cooldown to zero to disable its suppression (not to change authorization/robots checks).
- A fully skipped live lookup does not repeat the retrieval pass. Live retrieval that may have added records still re-queries SQLite. If the model has already abstained and the evidence is identical after a live search, it is not called a second time. New or changed evidence is still considered, and a new user question gets a fresh retrieval and generation.
- Live lookup defaults to 30 seconds (previously 45); each LLM attempt defaults to 30 seconds (previously 40), with a total 60-second inference/fallback budget per generation. The overall chat orchestration deadline is still 100 seconds by default. Explicit existing environment overrides still apply. Shorter deadlines may stop a slow source or a slow model before completion; raise `AGENT_MAX_SECONDS` to 45 and `LLM_TIMEOUT_SECONDS` to 40, or increase `LLM_TOTAL_SECONDS`, for more patience. Paid live actor work may require a larger live deadline; manual ingestion is not affected. Cancellation of an actor includes best-effort abort cleanup.

There is no reduction in stored evidence detail, chunk length, number of retrieval candidates, conversational memory, grounding validation or maximum answer token budget. The app still intentionally withholds streamed answer text until validation. Progress events arrive while the answer is being researched. First semantic inference can be slow when the local multilingual model is downloading/loading; later distinct queries still require embedding, search, and inference. CPU work already started in a thread may finish after an async deadline.

## Diagnose latency

The chat response now includes `timings_ms` with `retrieval_ms`, `live_search_ms`, `generation_ms` and `total_ms`. The UI shows total RAG time in the completed message and a breakdown in **Research activity**; terminal chat prints the same timings. Retrieval includes repeated passes when necessary; live search includes network access, extraction and indexing; generation includes LLM attempts and validation. Total is measured inside the orchestrator, not browser/network time or initial API model validation. Structured logs include the same aggregate timings without printing user questions.

```bash
make local-check-ai
make search Q="DG1 Dubai amenities"
make chat
```

Use the same question and same model before/after to compare cold and warm behavior. If model inference dominates, compare available free models with the existing model selector. If live lookup dominates, inspect tool activity; improve authorized initial corpus coverage rather than relaxing grounding. As an explicit user choice, disabling live lookup for a query tests local knowledge only; the assistant will abstain rather than invent missing details.

## Verification scope

Regression tests cover provider defaults, lazy catalogue lookup, continued free-only fallback, concurrent branches, query embedding cache identity, unchanged-evidence abstention and access cooldowns. Existing tests cover structured listing filters and RAG grounding. Real OpenRouter latency, Wasalt access, embedding download and actual Docker/Next.js runtime require the operator's network, dependencies and credentials. No production latency benchmark or guarantee is claimed.
