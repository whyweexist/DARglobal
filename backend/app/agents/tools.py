"""Backend-owned bounded discovery; no arbitrary user-provided fetch URLs."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from app.core.config import settings
from app.ingestion.crawler import discover_sitemap, eligible_link
from app.ingestion.parser import parse_html
from app.ingestion.policy import USER_AGENT, PolicyDenied, SourcePolicy, permitted_request
from app.rag.indexer import upsert_page
from app.rag.retrieval import significant_tokens

log = logging.getLogger(__name__)


@dataclass
class SearchActivity:
    tool: str
    status: str
    detail: str
    found: int = 0

    def public(self) -> dict:
        return vars(self)


async def discover_and_ingest(query: str, sources: list[str], *, max_pages: int | None = None) -> list[SearchActivity]:
    """Search official sitemap URL slugs and fetch a bounded subset, if permitted."""
    budget = min(max_pages or settings().agent_max_live_pages, settings().agent_max_live_pages)
    terms = set(significant_tokens(query))
    activities = []
    if budget <= 0:
        return [SearchActivity("discover_official_source_pages", "skipped", "Live discovery disabled")]
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=False,
                                  trust_env=False, timeout=12) as client:
        policy = SourcePolicy(client)
        for source in sources:
            if budget <= 0:
                break
            if source == "wasalt" and not settings().wasalt_permitted:
                activities.append(SearchActivity("discover_official_source_pages", "permission_required",
                                                 "Wasalt requires documented authorized collection"))
                continue
            if source == "darglobal" and not settings().darglobal_enabled:
                activities.append(SearchActivity("discover_official_source_pages", "disabled", "DarGlobal disabled"))
                continue
            base = "https://darglobal.co.uk" if source == "darglobal" else "https://wasalt.sa"
            try:
                urls = await discover_sitemap(client, policy, base + "/sitemap.xml", source, 120)
                ranked = sorted((u for u in urls if eligible_link(source, u)),
                                key=lambda u: sum(t in urlparse(u).path.lower() for t in terms), reverse=True)
                targeted = [u for u in ranked if sum(t in urlparse(u).path.lower() for t in terms)]
                if not targeted:
                    activities.append(SearchActivity("discover_official_source_pages", "no_match",
                                                     f"No matching authorized sitemap URLs found for {source}"))
                    continue
                count = 0
                for url in targeted[:budget]:
                    try:
                        html = await permitted_request(client, policy, url, source)
                        page = parse_html(html, source)
                        if page.sections:
                            upsert_page(source, url, page, method="on_demand_crawl")
                            count += 1
                            budget -= 1
                    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                        log.warning("on-demand fetch failed for %s: %s", source, type(exc).__name__)
                activities.append(SearchActivity("discover_official_source_pages", "completed" if count else "no_match",
                                                 f"Authorized official pages processed: {count}", count))
            except PolicyDenied as exc:
                activities.append(SearchActivity("discover_official_source_pages", "permission_required", str(exc)))
            except (httpx.HTTPError, ValueError) as exc:
                activities.append(SearchActivity("discover_official_source_pages", "unavailable", type(exc).__name__))
    return activities
