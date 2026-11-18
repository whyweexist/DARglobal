"""Bounded, permission-aware crawler that only follows source-specific official URLs."""
from __future__ import annotations
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urldefrag
import xml.etree.ElementTree as ET
import httpx
from app.core.config import settings
from app.ingestion.policy import SourcePolicy, PolicyDenied, ChallengeBlocked, USER_AGENT, reject_challenge, validate_official_url
from app.ingestion.parser import parse_html
from bs4 import BeautifulSoup
from app.ingestion.fetchers import ScraplingCrawlSession, fetch_allowed_page, require_engine, scrapling_available
from app.rag.indexer import upsert_page
from app.ingestion import wasalt_site

log = logging.getLogger(__name__)


@dataclass
class CrawlReport:
    source: str
    engine: str = "httpx"
    status: str = "complete"
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    detail: str = ""
    urls: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


def eligible_link(source: str, url: str) -> bool:
    if source == "wasalt":
        return wasalt_site.canonical_url(url) is not None
    p = urlparse(url)
    path = p.path.lower()
    if not path or path == "/":
        return True
    if any(path.endswith(e) for e in (".jpg", ".png", ".pdf", ".webp", ".svg", ".xml", ".zip", ".mp4")):
        return False
    if any(x in path for x in ("/login", "/signup", "/account", "/privacy", "/terms", "/contact", "/cookies")):
        return False
    return True


DARGLOBAL_CATALOG = "https://darglobal.co.uk/projects"


def catalog_links(html: str, base: str, source: str) -> dict[str, str]:
    """Use visible official anchor labels, not just slugs (e.g. /dg1)."""
    if source == "wasalt":
        return wasalt_site.listing_links(html, base)
    links = {}
    allowed = {"darglobal": {"darglobal.co.uk", "www.darglobal.co.uk"},
               "wasalt": {"wasalt.sa", "www.wasalt.sa"}}[source]
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a[href]")[:500]:
        label = a.get_text(" ", strip=True)
        u = urldefrag(urljoin(base, str(a['href'])))[0].split('?')[0]
        parts = urlparse(u)
        if parts.scheme != 'https' or parts.hostname not in allowed or not eligible_link(source, u):
            continue
        if label and parts.path not in ('', '/', '/projects'):
            links[u] = (links.get(u, '') + ' ' + label).strip()[:600]
    return links


def failure_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "HTTP request timed out"
    if isinstance(exc, (PolicyDenied, ValueError, RuntimeError)):
        return str(exc)[:250]
    return type(exc).__name__


async def discover_sitemap(client: httpx.AsyncClient, policy: SourcePolicy, url: str, source: str,
                           limit: int, depth: int = 0) -> list[str]:
    if depth > 1:
        return []
    try:
        validate_official_url(url, source)
        await policy.check(url, source)
        response = await client.get(url, timeout=12, follow_redirects=False)
        reject_challenge(response.headers, response.status_code, response.text[:16000])
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            return []
        root = ET.fromstring(response.content)
        locs = [n.text.strip() for n in root.iter() if (n.tag.endswith("}loc") or n.tag == "loc") and n.text]
        result: list[str] = []
        if root.tag.endswith("sitemapindex"):
            for child in locs[:4]:
                result.extend(await discover_sitemap(client, policy, child, source, limit, depth + 1))
                if len(result) >= limit:
                    break
        else:
            for loc in locs:
                try:
                    validate_official_url(loc, source)
                except PolicyDenied:
                    continue
                if eligible_link(source, loc):
                    result.append(loc)
                if len(result) >= limit:
                    break
        return result[:limit]
    except ChallengeBlocked:
        raise
    except (httpx.HTTPError, ValueError, ET.ParseError, PolicyDenied) as exc:
        log.info("sitemap discovery skipped (%s)", type(exc).__name__)
        return []


async def crawl(source: str, base_url: str, *, max_pages: int | None = None,
                dry_run: bool = False, discover_only: bool = False,
                engine: str | None = None) -> CrawlReport:
    config = settings()
    selected_engine = require_engine(engine or config.scraper_engine)
    report = CrawlReport(source=source, engine=selected_engine)
    limit = max_pages or config.crawl_max_pages
    # Explicit permission gate happens before ANY network access.
    try:
        validate_official_url(base_url, source)
    except PolicyDenied as exc:
        report.status, report.detail = "permission_required", str(exc)
        return report
    if selected_engine == "scrapling" and not (dry_run or discover_only) and not scrapling_available():
        report.status = "unavailable"
        report.detail = 'Scrapling fetcher is not installed (enable optional dependency and rebuild)'
        report.errors = 1
        return report
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml"},
                                  trust_env=False, limits=httpx.Limits(max_connections=3)) as client, ScraplingCrawlSession() as session:
        policy = SourcePolicy(client)
        sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
        try:
            seeds = await discover_sitemap(client, policy, sitemap_url, source, limit * 3)
        except ChallengeBlocked as exc:
            report.status, report.detail, report.errors = "access_restricted", str(exc), 1
            report.failures.append({"url": sitemap_url, "reason": str(exc)})
            return report
        # No sitemap access means crawl only from the official, permitted homepage.
        candidates = deque(([DARGLOBAL_CATALOG, base_url] if source == "darglobal" else [base_url]) + seeds)
        seen = set()
        while candidates and report.fetched < limit and len(seen) < limit * 8:
            current = candidates.popleft()
            current = urldefrag(current)[0].split("?")[0] or base_url
            if current in seen:
                continue
            seen.add(current)
            if not eligible_link(source, current):
                continue
            try:
                validate_official_url(current, source)
                if dry_run or discover_only:
                    await policy.check(current, source)
                    report.urls.append(current)
                    report.fetched += 1
                    continue
                fetched = await fetch_allowed_page(client, policy, current, source, engine=selected_engine, session=session)
                report.fetched += 1
                report.urls.append(current)
                parsed = parse_html(fetched.html, source, url=fetched.url)
                if parsed.sections:
                    outcome = upsert_page(source, fetched.url, parsed, method=f"authorized_{selected_engine}_crawl")
                    setattr(report, outcome, getattr(report, outcome) + 1)
                else:
                    report.skipped += 1
                if source == 'darglobal' and urlparse(current).path.rstrip('/') == '/projects':
                    # Product card links are more useful than arbitrary sitemap order.
                    project_urls = catalog_links(fetched.html, fetched.url, source)
                    for href, label in reversed(list(project_urls.items())):
                        if len(label.split()) >= 3 and href not in seen:
                            candidates.appendleft(href)
                if len(candidates) < limit * 5:
                    for link in fetched.links:
                        href = urldefrag(urljoin(fetched.url, link))[0]
                        try:
                            validate_official_url(href, source)
                            if eligible_link(source, href) and href not in seen:
                                candidates.append(href)
                        except PolicyDenied:
                            continue
                await asyncio.sleep(config.crawl_delay_seconds)
            except PolicyDenied as exc:
                report.skipped += 1
                report.failures.append({"url": current, "reason": failure_reason(exc)})
                if report.fetched == 0 and "robots.txt" in str(exc):
                    report.status, report.detail = "permission_required", str(exc)
                    break
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                report.errors += 1
                report.failures.append({"url": current, "reason": failure_reason(exc)})
                log.warning("crawl error: source=%s url=%s type=%s", source, current, type(exc).__name__)
                if isinstance(exc, ChallengeBlocked) or any(f"HTTP {code}" in failure_reason(exc) for code in (401, 403, 429)):
                    break
        if any("Cloudflare security challenge" in f["reason"] for f in report.failures):
            report.status = "access_restricted"
        if report.errors and report.status == "complete":
            report.status = "partial" if report.fetched else "unavailable"
        if report.failures and not report.detail:
            report.detail = "; ".join(f["reason"] for f in report.failures[:3])
    return report
