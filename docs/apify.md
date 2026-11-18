# Wasalt via the approved Apify data provider

The optional adapter uses the documented [Saudi Real Estate Actor](https://apify.com/constructive_calm/saudi-real-estate-scraper), its [input schema](https://apify.com/constructive_calm/saudi-real-estate-scraper/input-schema), and the [Apify run API](https://docs.apify.com/api/v2/actors-runs-post). It calls the actor and reads its default dataset. The actor is community maintained; its public listing is not independent proof of Wasalt endorsement. Enable it only if your actual approval covers the actor, use of the returned public listing information, and the intended retention/attribution.

## Setup

Preserve `.env` and the existing `data/` directory when upgrading. Do not put either token into source control or frontend code. Copy the following configuration into `.env`, replacing values with actual credentials/authorization:

```dotenv
WASALT_AUTHORIZED=true
WASALT_AUTHORIZATION_REFERENCE="Your genuine approved data-provider scope/reference"
WASALT_ENGINE=apify
APIFY_ENABLED=true
APIFY_TOKEN=your_actual_apify_api_token
APIFY_MAX_LISTINGS=40
APIFY_MAX_RUNS_PER_DAY=4
APIFY_MAX_CHARGE_USD=0.25
APIFY_LIVE_SEARCH=false
SCRAPER_ENGINE=scrapling
ENABLE_SCRAPLING=true
CRAWL_MAX_PAGES=50
```

Use `SCRAPER_ENGINE=httpx` instead if you do not need Scrapling for DarGlobal. `WASALT_ENGINE=inherit` uses the global engine. `WASALT_ENGINE=httpx` or `scrapling` selects direct approved HTTP collection instead. An access refusal is not a reason to switch automatically to another access method. The provider is selected explicitly by the operator. No new Python dependency is needed for Apify (HTTPX is already present).

## Native CLI

```bash
make local-doctor
make local-scrape-wasalt ARGS="--engine apify --dry-run --max-pages 10"
make local-scrape-wasalt ARGS="--engine apify --max-pages 40 --query 'apartments for sale in Riyadh'"
make local-index
make stats
make export
make search Q="Wasalt apartments for sale in Riyadh with 2 bedrooms under 1 million SAR" ARGS="--source wasalt"
make local
```

A dry run validates configuration and prints the planned actor input, without contacting or charging Apify. `--max-pages` means maximum listing records in Apify mode, not HTML pages. The configured `APIFY_MAX_LISTINGS` is a hard application cap on accepted records per run. For a broader corpus, make separate approved, budgeted queries for rentals, different cities and property categories. Collection is intentionally bounded, not a whole-market data dump. For deeper DarGlobal content refresh with `make local-scrape-darglobal ARGS="--max-pages 50"`; this walks project detail pages using the selected official-source HTTP engine. Old documents are re-chunked when re-ingested, not upon FTS-only reindex. Run `make local-index` again if more vector chunks remain (150 per batch). Preserve SQLite.

Docker equivalents: `make scrape-wasalt ARGS="--engine apify --dry-run --max-pages 10"`, `make scrape-wasalt ARGS="--engine apify --max-pages 40"`, `make index`, `make up`. The environment is passed server-side by Compose. In production put these keys in `.env.production` and follow the existing production deployment guide. If you want only one manual run before serving the app, keep `SCRAPE_ON_BOOT=false` and use `APIFY_ENABLED=false` after ingestion; the scheduler uses the configured provider and will refresh when due if enabled. No direct automatically attempted fallback from a Wasalt challenge to the paid actor is implemented.

## Cost and chat lookup

The actor is metered (its store currently advertises pricing from $4 per 1,000 listing events). Apify account credits, actor charges, and platform usage are distinct; verify the actor price and Apify account spending settings before launching. A free account does not guarantee zero cost. The code passes `maxTotalChargeUsd` per run and enforces a durable, UTC-day run-attempt quota in the same SQLite file; these do not guarantee a cap on all possible platform charges. Use Apify account-level spending limits as well. A failed submission counts against the application run quota; no automatic paid retry. User-triggered runs are disabled by default. Only set `APIFY_LIVE_SEARCH=true` if you explicitly accept the cost from chatbot requests. The live RAG agent has a shorter deadline and a separate record cap via `APIFY_LIVE_MAX_LISTINGS`. The actor is fixed to `platforms=["wasalt"]`; proxy use and unrelated platform enrichment are disabled. No access credentials are sent to Wasalt or exposed to the UI.

## Data contract and retrieval

The adapter validates the platform and official HTTPS source URL, requires a provider observation time and title, discards non-Wasalt rows and actor summary records, and keeps only whitelisted public listing fields. Contact fields and raw provider payloads are not persisted. Free text is scrubbed for URLs, emails, and common Saudi mobile patterns (not a guarantee of complete PII detection; review the authorized content before publishing). Each listing yields a facts section, an amenities/status section if present, and published descriptions when provided. Query parsing supports English and common Arabic terms, bounded price filters including million/thousand suffixes, property categories, sale/rent, cities, and exact bedroom counts in SQLite. All Wasalt search branches use these filters for marketplace queries. More complex statistical queries still require evidence and must not be represented as comprehensive market analyses. The model is instructed to attribute Wasalt.sa and distinguish observed asking prices from current availability. Every answer must point to actual source URLs.

Important: the actor documentation states that full Wasalt seller-written descriptions are not fetched and many listings have no description. This method cannot create missing amenities, availability or project specifications. It does not currently provide a complete Wasalt project-detail catalogue. Use an additional approved detailed feed where required; do not guess. For current listing status, visit the linked Wasalt listing. No real actor run was executed in the build environment; the HTTP contract tests use isolated fixtures only. The frontend and complete deployment require Codespaces runtime verification.
