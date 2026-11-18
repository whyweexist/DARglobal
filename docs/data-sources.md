# Source ingestion, permission and provenance

## DarGlobal

- Website: https://darglobal.co.uk/
- Adapter: `app.ingestion.darglobal`
- CLI: `scripts/scrape_darglobal.py`
- Policy: official HTTPS hosts, live robots.txt verification, bounded sitemap/anchor traversal, per-hop redirect validation and no bypass mechanisms, low request rate, source attribution.
- Website terms and content rights must be independently reviewed by the operator before deployment. `DARGLOBAL_ENABLED` represents administrative configuration, not a general grant of content rights.

## Wasalt

- Website: https://wasalt.sa/
- Terms: https://wasalt.sa/en/s/terms-and-conditions ; see also https://wasalt.sa/en/s/terms-of-use
- Adapter: `app.ingestion.wasalt`
- CLI: `scripts/scrape_wasalt.py`
- Default **blocked**. Wasalt's terms restrict automated data extraction and reuse. Obtain appropriate written authorization before enabling collection.
- `WASALT_AUTHORIZED=true` **and** `WASALT_AUTHORIZATION_REFERENCE=...` provide an administrative attestation, not independent verification. The operator must retain the actual permission document securely.
- Authorized export alternative: CSV/JSON with source `url`, `title`, `content` and optional `language`. The import also requires an authorization reference.

### Dedicated marketplace ingestion

The updated adapter is split into `wasalt.py` (crawl scheduling), `wasalt_site.py` (public URL discovery, canonicalization, category selection, bounded pagination), and `wasalt_parser.py` (listing/project extraction). It starts with sale/rent category pages, interleaves detail pages across cities, extracts known property facts from individual descriptions and matching JSON-LD, and indexes actual visible category card labels separately. Project ranges and starting prices are retained as qualified text rather than exact prices. Missing facts remain absent. The property row and text index are committed together. Related-property prices, contact links, and broker/license fields are excluded by the targeted parser. No browser automation or private endpoints are used.

Public route patterns checked against official pages during the update:

- `https://wasalt.sa/en/apartments-for-sale-in-riyadh`
- `https://wasalt.sa/en/properties-for-rent-in-jeddah`
- `/en/property/sale/<slug>` and `/en/property/rent/<slug>`
- `/en/project/<city>/<slug>`
- Public category pagination uses `?page=N`; only advertised/visible next pages are followed, with a bounded maximum.

Optional `--query` selects a city, property type and sale/rent category. `WASALT_DETAILS_PER_CATEGORY`, `WASALT_MAX_CATEGORY_PAGES`, and `WASALT_MAX_RESPONSE_BYTES` control the page budget and response limit. The underlying English routes may contain Arabic listing descriptions; both are retained. Source-specific routing also applies to on-demand discovery. No live Wasalt integration run is claimed: current raw HTML and robots policies must be verified from the running Codespace. The offline fixtures model the public page structure, not actual property records. JS-only content, access-denied pages, and unadvertised fields can still be unavailable. Import an authorized data export if direct access does not succeed.


## Selectable crawling engines

Both official-source adapters support `--engine httpx` (default) or
`--engine scrapling` (optional fetcher extra). Engine selection does **not**
change source access rules. HTTPX checks robots/sitemaps regardless of engine;
Scrapling uses asynchronous HTTP fetching and native CSS link selection only.
See [Scrapling integration](scrapling.md).

## Source metadata

The database records source status, last successful ingestion, page URL, SHA-256 hash, fetched time, language, ingestion method and last run report. The app separates `authorized_crawl`, `on_demand_crawl` and `authorized_import`.

## Compliance constraints

- No login bypass, CAPTCHAs, rotating proxies, private APIs or stealth browsers.
- Fail closed when robots.txt cannot be retrieved; site terms may be more restrictive than robots.
- No property fact fabrication, no `0` substituted for unknown prices.
- If a source is blocked, the research UI labels it as restricted and provides no purported source documents.
- Real data is not distributed in the repository. Local SQLite is populated only by successful authorized ingestion/import.
