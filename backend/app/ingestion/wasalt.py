"""Dedicated, bounded marketplace ingestion; all fetches use the shared policy."""
from __future__ import annotations
import asyncio
import logging
from collections import deque
import httpx
from app.core.config import settings
from app.ingestion.crawler import CrawlReport, failure_reason
from app.ingestion.fetchers import ScraplingCrawlSession, fetch_allowed_page, require_engine, scrapling_available
from app.ingestion.policy import PolicyDenied, SourcePolicy, USER_AGENT, assert_source_authorized
from app.ingestion.parser import parse_html
from app.ingestion.wasalt_site import canonical_url, kind, listing_links, next_page, seed_urls
from app.rag.indexer import upsert_page

log = logging.getLogger(__name__)


async def scrape_wasalt(*, max_pages: int | None = None, dry_run: bool = False,
                        engine: str | None = None, query: str = '') -> CrawlReport:
    cfg = settings()
    selected = engine or cfg.effective_wasalt_engine
    if selected == "apify":
        from app.ingestion.apify_wasalt import scrape_apify
        return await scrape_apify(max_pages=max_pages, dry_run=dry_run, query=query)
    selected = require_engine(selected)
    report = CrawlReport(source='wasalt', engine=selected)
    limit = cfg.crawl_max_pages if max_pages is None else max_pages
    if not 1 <= limit <= 250:
        raise ValueError('max_pages must be between 1 and 250')
    try:
        assert_source_authorized('wasalt')
    except PolicyDenied as exc:
        report.status, report.detail = 'permission_required', str(exc)
        return report
    if selected == 'scrapling' and not dry_run and not scrapling_available():
        report.status, report.detail, report.errors = 'unavailable', 'Scrapling fetcher is not installed', 1
        return report
    # Interleave a bounded number of details per category with the next city;
    # a busy first category must not consume the entire collection budget.
    categories = deque(seed_urls(query))
    details: deque[str] = deque()
    priority_details: deque[str] = deque()
    seen: set[str] = set()
    indexed = 0
    blocked = False
    async with httpx.AsyncClient(headers={'User-Agent': USER_AGENT,'Accept':'text/html'},trust_env=False,
                                 follow_redirects=False, timeout=15) as client, ScraplingCrawlSession() as session:
        policy = SourcePolicy(client)
        while (categories or details or priority_details) and len(seen) < limit:
            queue = priority_details or categories or details
            url = canonical_url(queue.popleft())
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                if dry_run:
                    await policy.check(url, 'wasalt')
                    report.urls.append(url)
                    continue
                page = await fetch_allowed_page(client, policy, url, 'wasalt', engine=selected, session=session)
                report.fetched += 1
                report.urls.append(page.url)
                parsed = parse_html(page.html, 'wasalt', url=page.url)
                if parsed.sections:
                    outcome = await asyncio.to_thread(upsert_page,'wasalt',page.url,parsed,f'authorized_{selected}_crawl')
                    setattr(report,outcome,getattr(report,outcome)+1)
                    indexed += 1
                else:
                    report.skipped += 1
                    report.failures.append({'url':url,'reason':'No listing-specific evidence extracted'})
                if kind(url) in ('home','category','search'):
                    links = listing_links(page.html,page.url)
                    found = [u for u in links if kind(u)=='detail' and u not in seen]
                    priority_details.extend(found[:cfg.wasalt_details_per_category])
                    details.extend(found[cfg.wasalt_details_per_category:])
                    nxt = next_page(url,page.html,cfg.wasalt_max_category_pages)
                    if nxt and nxt not in seen:
                        categories.append(nxt)
            except PolicyDenied as exc:
                report.skipped += 1
                report.failures.append({'url':url,'reason':failure_reason(exc)})
                blocked = True
                if 'robots.txt unavailable' in str(exc) or 'DNS lookup failed' in str(exc):
                    break
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                report.errors += 1
                reason = failure_reason(exc)
                report.failures.append({'url':url,'reason':reason})
                log.warning('Wasalt collection: %s %s',url,reason)
                # Do not try to get around access refusals or rate limits.
                if 'Cloudflare security challenge' in reason or any(f'HTTP {code}' in reason for code in (401,403,429)):
                    break
            finally:
                if not dry_run and len(seen)<limit:
                    await asyncio.sleep(cfg.crawl_delay_seconds)
    if dry_run:
        report.status = 'permission_required' if blocked else 'dry_run'
        report.detail = 'Policy checks only; no property pages fetched or stored'
    elif indexed == 0:
        report.status = 'permission_required' if blocked and not report.fetched else 'unavailable'
        report.detail = 'No Wasalt listing evidence indexed'
    elif report.failures:
        report.status = 'partial'
    if any("Cloudflare security challenge" in f["reason"] for f in report.failures):
        report.status = "access_restricted"
    if report.failures:
        report.detail = '; '.join(filter(None,[report.detail, *(f['reason'] for f in report.failures[:3])]))
    return report
