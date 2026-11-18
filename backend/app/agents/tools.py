"""Bounded official-source discovery using catalogue labels and sitemap links."""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from app.core.config import settings
from app.ingestion.crawler import DARGLOBAL_CATALOG, catalog_links, discover_sitemap, eligible_link, failure_reason
from app.ingestion.parser import parse_html
from app.ingestion.policy import USER_AGENT, PolicyDenied, SourcePolicy
from app.ingestion.fetchers import fetch_allowed_page
from app.rag.indexer import upsert_page
from app.rag.retrieval import significant_tokens
from app.ingestion.wasalt_site import seed_urls, kind as wasalt_kind
import re

log = logging.getLogger(__name__)

@dataclass
class SearchActivity:
    tool: str
    status: str
    detail: str
    found: int = 0

    def public(self) -> dict:
        return vars(self)


def rank_links(query: str, links: dict[str, str]) -> list[str]:
    terms = set(significant_tokens(query)) - {'darglobal', 'wasalt'}
    def score(u):
        words = set(significant_tokens(urlparse(u).path.replace('-', ' ') + ' ' + links[u]))
        return len(terms & words)
    return sorted((u for u in links if score(u)), key=score, reverse=True)


async def discover_and_ingest(query: str, sources: list[str], *, max_pages: int | None = None) -> list[SearchActivity]:
    cfg = settings()
    budget = min(cfg.agent_max_live_pages if max_pages is None else max_pages, cfg.agent_max_live_pages)
    activities = []
    name = 'discover_official_source_pages'
    if budget <= 0:
        return [SearchActivity(name, 'skipped', 'Live discovery disabled')]
    async with httpx.AsyncClient(headers={'User-Agent': USER_AGENT}, follow_redirects=False, trust_env=False, timeout=12) as client:
        policy = SourcePolicy(client)
        # An explicit marketplace question must not exhaust its live budget
        # on the developer catalogue before Wasalt is checked.
        prefer_wasalt = 'wasalt' in query.casefold() or bool(re.search(r'\b(?:riyadh|jeddah|dammam|makkah|madinah|rent|rental|sar)\b|الرياض|جدة|إيجار',query,re.I))
        if prefer_wasalt and 'darglobal' not in query.casefold():
            sources = sorted(sources,key=lambda x:x != 'wasalt')
        authorized = [s for s in sources if (s == 'wasalt' and cfg.wasalt_permitted) or (s == 'darglobal' and cfg.darglobal_enabled)]
        for source in sources:
            if source == 'wasalt' and not cfg.wasalt_permitted:
                activities.append(SearchActivity(name, 'permission_required', 'Wasalt requires documented authorized collection'))
                continue
            if source == 'darglobal' and not cfg.darglobal_enabled:
                activities.append(SearchActivity(name, 'disabled', 'DarGlobal disabled'))
                continue
            if budget <= 0:
                activities.append(SearchActivity(name, 'skipped', f'{source}: live page budget exhausted'))
                continue
            base = 'https://darglobal.co.uk' if source == 'darglobal' else 'https://wasalt.sa'
            entries = [DARGLOBAL_CATALOG] if source == 'darglobal' else seed_urls(query)
            entry = entries[0]
            # Reserve at least one fetch for another enabled source, if possible.
            remaining_sources = len(authorized) - authorized.index(source) - 1
            source_budget = max(1, budget - remaining_sources)
            blocked = False
            links = {}
            count = 0
            failures = []
            attempted = set()

            async def process(url):
                nonlocal budget, count, source_budget, blocked
                budget -= 1
                source_budget -= 1
                attempted.add(url)
                try:
                    page = await fetch_allowed_page(client, policy, url, source, engine=cfg.scraper_engine)
                    links.update(catalog_links(page.html, page.url, source))
                    parsed = parse_html(page.html, source, url=page.url)
                    if not parsed.sections:
                        failures.append(f'{url}: no extractable content')
                        return
                    outcome = await asyncio.to_thread(upsert_page, source, page.url, parsed, f'on_demand_{page.engine}_crawl')
                    count += 1
                    activities.append(SearchActivity('fetch_official_source_page', 'completed', f'{page.url}: {outcome}', 1))
                except PolicyDenied as exc:
                    failures.append(f'{url}: {failure_reason(exc)}')
                    activities.append(SearchActivity('fetch_official_source_page', 'permission_required', failures[-1]))
                    if 'robots.txt unavailable' in str(exc) or 'DNS lookup failed' in str(exc):
                        blocked = True
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    failures.append(f'{url}: {failure_reason(exc)}')
                    activities.append(SearchActivity('fetch_official_source_page', 'fetch_failed', failures[-1]))
                    if any(f'HTTP {code}' in failures[-1] for code in (401,403,429)):
                        blocked = True
                if budget > 0 and source_budget > 0 and not blocked:
                    await asyncio.sleep(cfg.crawl_delay_seconds)

            await process(entry)
            ranked = rank_links(query, links)
            if source == 'wasalt':
                # Category labels and actual listing cards are stronger than
                # unrelated sitemap URLs. Query-targeted categories may have
                # opaque/Arabic project slugs, so use card candidates too.
                ranked = [u for u in ranked if wasalt_kind(u)=='detail']
                ranked += [u for u in links if wasalt_kind(u)=='detail' and u not in ranked]
                ranked += [u for u in entries[1:] if u not in ranked]
            if not ranked and budget > 0 and source_budget > 0 and not blocked and source == 'darglobal':
                urls = await discover_sitemap(client, policy, base + '/sitemap.xml', source, 120)
                links.update({u: '' for u in urls if eligible_link(source, u) and u not in links})
                ranked = rank_links(query, links)
            for url in ranked:
                if budget <= 0 or source_budget <= 0 or blocked:
                    break
                if url not in attempted:
                    await process(url)
            detail = f'{source}: {len(attempted)} attempted, {count} usable pages, {len(failures)} failures'
            if failures:
                detail += '; ' + '; '.join(failures[:2])
            activities.append(SearchActivity(name, 'completed' if count else ('fetch_failed' if failures else 'no_match'), detail, count))
    return activities
