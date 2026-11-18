# Troubleshooting

## Repeated evidence-only answers or no new model answer

Older releases used a generic fallback message whenever all LLM calls failed or
failed output validation. That message was **not** a new AI-generated answer.
Starting a new conversation could therefore still show the same homepage excerpt.
This release deduplicates retrieval, filters generic source-name overlap, and returns
a specific error reason instead of repeating source passages in the chat bubble.

1. Configure `OPENROUTER_API_KEY` in the repository-root `.env` or your shell environment. Never commit the key.
2. Restart the app after editing the environment. Use `make local` for native mode or `make up` for Docker.
3. Run `make local-check-ai` (native) or `make check-ai` (Docker). This uses one real free-model request without requiring any indexed data.
4. For native mode, run `make stats`, `make local-ingest`, `make local-index`, and `make search Q="your question"` to inspect the data/retrieval layer. For Docker use `make refresh` and `make index`, preserving the data volume.

Common response reasons:

| Reason | Meaning / next action |
|---|---|
| `llm_unconfigured` | Key missing; configure and restart. |
| `llm_auth_error` | OpenRouter rejected access; check credentials or permissions. |
| `budget_or_account_error` | Account/key budget or credit issue; check OpenRouter account settings. |
| `rate_limited` | Provider quota; wait or choose another available free model. |
| `provider_timeout`, `provider_unavailable` | Provider/network issue; retry or select another listed free model. |
| `missing_or_invalid_citation`, `unsupported_numeric_claim` | Model output failed evidence validation. Try a different model or improve source coverage. Do not disable grounding. |
| `no_evidence`, `insufficient_evidence` | No adequate authorized records; inspect retrieval and source permissions. |

A successful direct model check does not guarantee source coverage or grounding.
A populated SQLite database does not guarantee that the selected provider can infer.
Actual project facts can only be generated when both layers work.

## Native mode

`make local` opens port 3000 and uses `data/estate.db`. Stop any Docker instance
using the same ports. Run `make local-setup` again if you enable Scrapling or
change dependencies. The first dependency and embedding download requires network
access. Use `make local-api` for API-only work or `make chat` for terminal-only work
after creating the index. Native and Docker databases are intentionally separate.

## Docker build times out downloading `nvidia-cusparse`

Symptom: `uv pip install --system --no-cache .` attempts to download multiple
`nvidia-*` CUDA dependencies while installing `sentence-transformers`.

Cause: Linux x86_64 default PyPI PyTorch is CUDA-enabled. This application
uses CPU-only embedding inference. The updated Dockerfile sets `UV_TORCH_BACKEND=cpu`
for x86_64 and verifies `torch.version.cuda is None`.

Rebuild in Codespaces:

```bash
docker compose build --no-cache api
make up
```

The container still downloads a CPU PyTorch wheel, but no NVIDIA libraries.
A timeout fetching the official PyTorch CPU index means network connectivity
needs to be fixed or the build retried; do not switch back to CUDA PyPI wheels.

For a local project-mode install, `backend/pyproject.toml` contains the CPU index
selection. Existing virtual environments with CUDA torch may need recreation.
