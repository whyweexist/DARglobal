#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v uv >/dev/null || { echo 'Install uv: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
[ -f .env ] || cp .env.example .env
mkdir -p "$ROOT/data" "$ROOT/data/exports" "$ROOT/data/backups"
# Native data storage is explicit and is deliberately separate from Docker's volume.
export DATABASE_URL="sqlite:///$ROOT/data/estate.db"
export HF_HOME="$ROOT/data/models-cache" UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=5
export API_URL_INTERNAL="http://127.0.0.1:8000"
mode="${1:-up}"; if [ "$#" -gt 0 ]; then shift; fi
# An explicit per-run --engine scrapling also needs the optional extra.
# Existing virtual environments must not cause the installation to be skipped.
extras=()
want_scrapling=false
if [ "${ENABLE_SCRAPLING:-}" = true ] || [ "${SCRAPER_ENGINE:-}" = scrapling ] || [ "${WASALT_ENGINE:-}" = scrapling ] || \
   grep -Eq "^[[:space:]]*((SCRAPER_ENGINE|WASALT_ENGINE)[[:space:]]*=[[:space:]]*['\"]?scrapling['\"]?|ENABLE_SCRAPLING[[:space:]]*=[[:space:]]*['\"]?true['\"]?)[[:space:]]*(#.*)?$" .env; then
  want_scrapling=true
fi
previous=""
for arg in "$@"; do
  if [ "$arg" = --engine=scrapling ] || { [ "$previous" = --engine ] && [ "$arg" = scrapling ]; }; then
    want_scrapling=true
  fi
  previous="$arg"
done
needs_setup=false
if [ "$mode" = setup ] || [ ! -x backend/.venv/bin/python ]; then needs_setup=true; fi
if [ "$want_scrapling" = true ]; then
  extras+=(--extra scrapling)
  if ! backend/.venv/bin/python -c 'from scrapling.fetchers import FetcherSession' >/dev/null 2>&1; then
    needs_setup=true
  fi
fi
if [ "$needs_setup" = true ]; then
  (cd backend && uv sync "${extras[@]}" --extra dev)
  (cd backend && uv run --no-sync python -c 'import torch; assert torch.version.cuda is None, "Expected CPU-only PyTorch"')
  if [ "$want_scrapling" = true ]; then
    (cd backend && uv run --no-sync python -c 'from scrapling.fetchers import FetcherSession; from importlib.metadata import version; print("Scrapling", version("scrapling"))')
  fi
fi
backend() { (cd "$ROOT/backend" && uv run --no-sync --env-file "$ROOT/.env" "$@"); }
case "$mode" in
  setup) exit 0;;
  cli) backend python -m app.cli "$@"; exit $?;;
  scrape-darglobal|scrape-wasalt)
    backend python "$ROOT/scripts/${mode//-/_}.py" "$@"; exit $?;;
  up|api)
    backend alembic upgrade head
    backend python -m app.cli bootstrap
    if [ "$mode" = api ]; then
      cd backend; exec uv run --no-sync --env-file "$ROOT/.env" uvicorn app.main:app --host 0.0.0.0 --port 8000
    fi
    command -v pnpm >/dev/null || { echo 'Install pnpm 9 and Node.js 22 for the frontend (or run make local-api).' >&2; exit 1; }
    (cd frontend && pnpm install --no-frozen-lockfile)
    pids=()
    cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; wait || true; }
    trap cleanup EXIT
    trap 'exit 130' INT TERM
    (cd backend; exec uv run --no-sync --env-file "$ROOT/.env" uvicorn app.main:app --host 0.0.0.0 --port 8000) & pids+=("$!")
    for i in $(seq 1 60); do
      if curl --silent --fail http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then break; fi
      if ! kill -0 "${pids[0]}" 2>/dev/null; then echo 'Backend failed to start' >&2; exit 1; fi
      sleep 1
    done
    curl --silent --fail http://127.0.0.1:8000/api/v1/health/ready >/dev/null
    (cd backend; exec uv run --no-sync --env-file "$ROOT/.env" python -m app.worker) & pids+=("$!")
    (cd frontend; exec pnpm dev) & pids+=("$!")
    echo 'Native UI: http://localhost:3000 | API: http://localhost:8000/docs | Database: data/estate.db'
    wait -n "${pids[@]}";;
  *) echo 'Usage: scripts/local.sh {setup|up|api|cli|scrape-darglobal|scrape-wasalt}' >&2; exit 2;;
esac
