"""Swappable, permission-aware HTML fetch/parse engines.

Scrapling is **opt-in** and uses only its lightweight async HTTP fetcher.
Neither engine performs browser/stealth/CAPTCHA/proxy bypass. Robots, source
permissions and official-host policy are checked *before every redirect hop*.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.ingestion.policy import (
    PolicyDenied,
    SourcePolicy,
    USER_AGENT,
    permitted_request,
    reject_challenge,
    validate_official_url,
)

log = logging.getLogger(__name__)
ENGINE_NAMES = ("httpx", "scrapling")
MAX_RESPONSE_BYTES = 1_500_000


@dataclass(frozen=True)
class FetchedPage:
    url: str
    html: str
    links: list[str]
    engine: str


class FetchFailed(RuntimeError):
    """An expected fetch/response failure; never a signal to bypass policy."""


def require_engine(engine: str) -> str:
    if engine not in ENGINE_NAMES:
        raise ValueError(f"Unknown scraping engine: {engine!r}; choose httpx or scrapling")
    return engine


def scrapling_available() -> bool:
    """Report whether the *optional fetchers extra* is installed."""
    try:
        from scrapling.fetchers import FetcherSession  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


class ScraplingCrawlSession:
    """Lazily create one documented async FetcherSession per crawl.

    Authorization is checked by the caller before opening the session. The
    context owns its lifecycle, including an exception or cancellation.
    """

    def __init__(self) -> None:
        self.stack = AsyncExitStack()
        self._session: Any = None

    async def __aenter__(self) -> ScraplingCrawlSession:
        await self.stack.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        try:
            await self.stack.__aexit__(*args)
        finally:
            self._session = None

    async def get(self, url: str) -> Any:
        if self._session is None:
            try:
                from scrapling.fetchers import FetcherSession
            except (ImportError, OSError) as exc:
                raise FetchFailed(
                    'Scrapling fetcher not installed or cannot load; run make local-setup '
                    'with ENABLE_SCRAPLING=true or rebuild Docker with the extra'
                ) from exc
            # Explicitly identify the application. Do not impersonate browsers,
            # auto-follow redirects, retry refusals, or solve security challenges.
            self._session = await self.stack.enter_async_context(FetcherSession(
                impersonate=None,
                stealthy_headers=False,
                follow_redirects=False,
                retries=1,
                timeout=15,
                verify=True,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            ))
        return await self._session.get(url)


async def fetch_allowed_page(
    client: httpx.AsyncClient,
    policy: SourcePolicy,
    url: str,
    source: str,
    *,
    engine: str = "httpx",
    size_limit: int | None = None,
    session: ScraplingCrawlSession | None = None,
) -> FetchedPage:
    """Get an official HTML page using the selected engine.

    The HTTPX engine uses bounded streaming. Scrapling's fetcher exposes the
    full response body; its body size is checked immediately after fetching.
    No silent HTTPX fallback occurs when Scrapling is unavailable or fails.
    """
    require_engine(engine)
    if size_limit is None:
        size_limit = settings().wasalt_max_response_bytes if source == "wasalt" else MAX_RESPONSE_BYTES
    validate_official_url(url, source)
    if engine == "httpx":
        final_url, html = await permitted_request(client, policy, url, source, size_limit=size_limit)
        links = [str(a["href"]) for a in BeautifulSoup(html, "lxml").find_all("a", href=True)[:250]]
        return FetchedPage(url=final_url, html=html, links=links, engine=engine)

    # The standalone helper also works outside a crawl, but batch callers
    # pass their own context so all requests reuse a single connection pool.
    if session is None:
        async with ScraplingCrawlSession() as owned:
            return await fetch_allowed_page(client, policy, url, source, engine=engine,
                                            size_limit=size_limit, session=owned)

    current = url
    for _ in range(4):
        await policy.check(current, source)
        try:
            response = await session.get(current)
        except FetchFailed:
            raise
        except Exception as exc:
            # Scrapling/curl_cffi exceptions are not httpx.HTTPError. Normalize
            # them so the crawler records failures instead of crashing ingestion.
            log.warning("Scrapling request failed: url=%s type=%s", current, type(exc).__name__)
            raise FetchFailed(f"Scrapling request failed ({type(exc).__name__})") from exc
        status = int(response.status)
        headers = httpx.Headers(dict(response.headers or {}))
        reject_challenge(headers, status)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location")
            if not location:
                raise FetchFailed("Redirect missing Location header")
            target = urljoin(current, location)
            validate_official_url(target, source)
            current = target
            continue
        if status != 200:
            raise FetchFailed(f"Scrapling received HTTP {status}")
        if "html" not in headers.get("content-type", "").lower():
            raise FetchFailed("Scrapling response is not HTML")
        body = response.body
        if not isinstance(body, bytes):
            raise FetchFailed("Scrapling response body is not bytes")
        if len(body) > size_limit:
            raise FetchFailed("Document exceeds allowed response size")
        # HTTPX honors an explicit response charset and falls back safely.
        html = httpx.Response(200, headers=headers, content=body).text
        reject_challenge(headers, status, html)
        try:
            links = [str(item) for item in response.css("a::attr(href)").getall()[:250] if item]
        except Exception as exc:
            raise FetchFailed(f"Scrapling CSS extraction failed ({type(exc).__name__})") from exc
        return FetchedPage(url=current, html=html, links=links, engine=engine)
    raise PolicyDenied("Too many redirects or redirect loop")
