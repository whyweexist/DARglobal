# REST and SSE API

API base: `/api/v1`, proxied through the same-origin Next.js host. Swagger: backend `/docs` (not exposed by default from browser proxy; use forwarded API in local development).

- `GET /health/live` — process liveness.
- `GET /health/ready` — SQLite and FTS availability, indexed document/chunk count and semantic/vector state.
- `GET /models` (or `GET /models?refresh=true`) — dynamic current free OpenRouter model catalog; route `openrouter/free` always offered.
- `GET /sources` or `/sources/status` — documented source state and real indexed counts.
- `GET /search?q=...&source=all` — read-only retrieval diagnostics, rate-limited.
- `POST /chat` — JSON response with answer, model, citation URLs, retrieval/tool states, conversation credentials, retrieval query, and a specific `reason` when applicable. A new conversation omits both conversation credentials; a follow-up supplies both from the previous response. Bounded prior turns are used only for dependent questions.
- `POST /chat/stream` — `text/event-stream`: `activity`, `delta`, `done`, `error` events.
- `GET /conversations/{id}` — conversation history, requires `X-Conversation-Token` header.
- `DELETE /conversations/{id}` — delete conversation, requires same token.

Request:

```json
{"message":"What projects are documented in Dubai?","model":"openrouter/free","source_filter":["darglobal","wasalt"],"allow_live_search":true}
```

The API always validates model IDs and source values server-side. Do not put OpenRouter credentials in the browser. Citation URLs originate from database documents only.
