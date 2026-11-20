# Deployment and GitHub Codespaces runbook

## A. GitHub Codespaces assessment preview

1. Create a GitHub repository and upload the contents of this archive into the repository root (preserve dotfiles).
2. From GitHub **Code → Codespaces → Create codespace**. This repository supplies `.devcontainer/devcontainer.json` with Python 3.12, Node 22, Docker-in-Docker and recommended extensions. Ensure your Codespace has adequate disk/RAM for PyTorch and a local embedding model (a 4-core/8-GB RAM instance is a more comfortable starting point than the smallest size; actual memory use depends on the selected model).
3. Add `OPENROUTER_API_KEY` through a secure Codespaces secret or into your local ignored `.env`. The free-model router works only if the account has available quota.
4. If you have a written Wasalt authorization, store it securely and configure `WASALT_AUTHORIZED` and `WASALT_AUTHORIZATION_REFERENCE`. Otherwise leave collection blocked.
5. Run `make up` from the project root. The command creates `.env` if missing, builds the two Docker images, runs the Alembic/bootstrap init service, checks source policies, indexes permitted content, and brings up API + worker + frontend.
6. Run `make status` and `make logs` to diagnose startup. Then open **Ports → 3000 → Open in browser**.
7. For a shareable preview, change port **3000** visibility to **Public** if your repository/account permits it. Copy the exact forwarded HTTPS URL. Test from a fresh incognito browser. Do not invent a preview URL.
8. `make smoke-test` executes requests against `http://localhost:3000` inside Codespaces.

The Codespace may stop automatically and its URL may become unavailable. This is suitable for assessment but not guaranteed always-on production hosting.

## Render Free single-container deployment

The root `render.yaml` Blueprint builds `Dockerfile.render`, which exports the
Next.js frontend and serves it from the FastAPI container on the same origin.
The image uses the Gemini HTTP embedding provider and does not install
PyTorch/SentenceTransformers. Set the `OPENROUTER_API_KEY` and
`EMBEDDING_API_KEY` secrets when creating the Render service; override
`EMBEDDING_PROVIDER` and optionally `EMBEDDING_API_URL` to use another supported
provider or compatible endpoint. The Free plan's filesystem is ephemeral, so
local SQLite data is not durable across instance replacement.

## B. Production Docker deployment (single persistent VPS)

### Prerequisites

- Linux VPS running a supported Ubuntu/Debian release with Docker Engine and Docker Compose plugin.
- A domain name such as `estate.example.com` with an `A`/`AAAA` DNS record pointing to the VPS.
- Firewall allowing TCP 80/443 plus SSH from trusted addresses.
- Recommended starting resources: 4 vCPU, 8GB RAM, 25GB disk, subject to measured model and OS demand; the local embedding model can make the cold image large.
- Hosting account and OpenRouter API key. This repository cannot provision credentials or hosting automatically.

### 1. Install Docker

Use the official Docker Engine and Compose installation instructions for your distro: https://docs.docker.com/engine/install/ . Verify `docker version` and `docker compose version`.

### 2. Place source code and persistent directories

```bash
sudo mkdir -p /opt/estate-intelligence /var/lib/estate-intelligence/data /var/lib/estate-intelligence/hf_cache
sudo chown -R 10001:10001 /var/lib/estate-intelligence/data /var/lib/estate-intelligence/hf_cache
cd /opt/estate-intelligence
# Clone your own repository here or securely extract the supplied archive.
```

### 3. Configure secrets

```bash
cp .env.production.example .env.production
chmod 600 .env.production
# Edit APP_DOMAIN, OPENROUTER_API_KEY, ALLOWED_ORIGINS, source permissions.
```

`ALLOWED_ORIGINS` must be your HTTPS domain. Confirm Wasalt's written authorization before enabling collection. The default production setting disables startup crawls; run a separately approved ingest/refresh operation to populate data.

### 4. HTTPS/reverse proxy

`Caddyfile` uses `{$APP_DOMAIN}`, passed by Compose. The Caddy container automatically requests and renews certificates when the public DNS and ports are correctly configured.

### 5. Launch production stack

```bash
set -a; . ./.env.production; set +a
# Or use the explicit Compose --env-file argument below for variable interpolation.
docker compose --env-file .env.production -f compose.prod.yaml up -d --build --wait
```

Start order: init migration/bootstrapping, API, worker, Next.js frontend, Caddy. Only Caddy binds public 80/443; backend and worker remain on the internal network.

### 6. Verify actual public endpoint

```bash
curl -fsS https://YOUR_REAL_DOMAIN/api/v1/health/live
curl -fsS https://YOUR_REAL_DOMAIN/api/v1/health/ready
curl -fsS https://YOUR_REAL_DOMAIN/api/v1/sources
curl -fsS https://YOUR_REAL_DOMAIN/api/v1/models
```

Open the URL in a fresh browser. Select a catalog-verified free model and ask a question supported by the source documents. Check citations and fallback behavior. No public URL should be claimed until tests actually succeed.

### 7. Refresh authorized source data

```bash
docker compose --env-file .env.production -f compose.prod.yaml exec worker python -m app.cli ingest --force
docker compose --env-file .env.production -f compose.prod.yaml exec worker python -m app.cli index
```

Each run reports actual status. Wasalt remains blocked without authorization.

### 8. Backup and recovery

See [operations.md](operations.md). Always create SQLite backups through the SQLite backup API rather than copying an active WAL database file.

### 9. Redeployment and rollback

Rebuild/deploy new images with `docker compose --env-file .env.production -f compose.prod.yaml up -d --build --wait`. Take a verified backup first. Rollback requires restoring compatible image tags (or source revision) and following the documented database migration compatibility plan. Do not down-migrate a live DB blindly.

### 10. Production hardening

Before public exposure implement an external rate limiter, abuse monitoring, an egress firewall that blocks private networks for source-fetching workloads, backup automation, secret rotation, and authentication appropriate to your user base. The default implementation is suitable as a controlled single-host assessment service, not a high-scale multi-tenant SaaS.

## C. Deployment failure diagnosis

- Init failed: inspect `docker compose logs init`, especially migrations, model downloads, permissions and insufficient disk.
- API unhealthy: inspect `/api/v1/health/ready` from inside API and confirm `/data` writable by UID 10001.
- No semantic retrieval: check `make doctor`, sqlite-vec installation, model downloads and RAM availability. FTS5 should remain active.
- Empty source index: ingestion may have been legally blocked or network/robots disallowed. Check `/api/v1/sources/status` before troubleshooting RAG.
- OpenRouter model picker only shows Auto: catalog endpoint unavailable or no confirmed free individual models; see backend logs.
- Caddy certificate errors: confirm DNS, incoming 80/443 and `APP_DOMAIN` environment variable.

## Optional Scrapling on production Docker

The production Compose build accepts `ENABLE_SCRAPLING` and the API/worker
receive `SCRAPER_ENGINE` from `.env.production`. To enable the optional
Scrapling HTTP engine, set both to `true` and `scrapling` respectively, then
**rebuild** with the documented production Compose command. No separate
Scrapling browser executable or Playwright installation is necessary.
Do not enable Wasalt collection without written source authorization.
See [Scrapling engine](scrapling.md).
