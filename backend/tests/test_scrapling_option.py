"""Test-only simulated Scrapling responses: no fabricated production data or network calls."""
import sys
from types import ModuleType
from urllib.parse import urlparse

import pytest
import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.ingestion.fetchers import FetchFailed, ScraplingCrawlSession, fetch_allowed_page, require_engine
from app.ingestion.policy import ChallengeBlocked, PolicyDenied
from app.ingestion.wasalt import scrape_wasalt


class AllowedPolicy:
    def __init__(self):
        self.checked = []

    async def check(self, url, source):
        self.checked.append((url, source))


class SelectedValues:
    def __init__(self, values):
        self.values = values

    def getall(self):
        return self.values


class FakePage:
    status = 200
    body = b'<html><body><a href="/project/a">A</a><main>Actual response is mocked only in tests</main></body></html>'
    headers = {'Content-Type': 'text/html; charset=utf-8'}

    def css(self, selector):
        assert selector == 'a::attr(href)'
        return SelectedValues(['/project/a'])


def install_fake_scrapling(monkeypatch, page):
    scraper = ModuleType('scrapling')
    fetchers = ModuleType('scrapling.fetchers')
    calls = []

    class FetcherSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(('open', kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            calls.append(('close', {}))

        async def get(self, url):
            calls.append((url, self.kwargs))
            return page

    fetchers.FetcherSession = FetcherSession
    monkeypatch.setitem(sys.modules, 'scrapling', scraper)
    monkeypatch.setitem(sys.modules, 'scrapling.fetchers', fetchers)
    return calls


def safe_test_url(url, source):
    if urlparse(url).hostname != 'darglobal.co.uk' or source != 'darglobal':
        raise PolicyDenied('Not an approved test source')
    return url


@pytest.mark.asyncio
async def test_scrapling_fetches_and_extracts_links(monkeypatch):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)
    calls = install_fake_scrapling(monkeypatch, FakePage())
    policy = AllowedPolicy()
    async with httpx.AsyncClient() as client:
        result = await fetch_allowed_page(client, policy, 'https://darglobal.co.uk/', 'darglobal', engine='scrapling')
    assert result.links == ['/project/a']
    assert result.engine == 'scrapling'
    assert '<main>' in result.html
    assert policy.checked == [('https://darglobal.co.uk/', 'darglobal')]
    assert calls[0][1]['follow_redirects'] is False
    assert calls[0][1]['stealthy_headers'] is False
    assert calls[0][1]['retries'] == 1


@pytest.mark.asyncio
async def test_scrapling_rejects_external_redirect(monkeypatch):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)

    class RedirectPage:
        status = 302
        headers = {'Location': 'https://attacker.example/hidden'}
        body = b''

    install_fake_scrapling(monkeypatch, RedirectPage())
    policy = AllowedPolicy()
    async with httpx.AsyncClient() as client:
        with pytest.raises(PolicyDenied):
            await fetch_allowed_page(client, policy, 'https://darglobal.co.uk/', 'darglobal', engine='scrapling')
    assert policy.checked == [('https://darglobal.co.uk/', 'darglobal')]


@pytest.mark.asyncio
async def test_scrapling_fails_on_oversized_html(monkeypatch):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)
    install_fake_scrapling(monkeypatch, FakePage())
    async with httpx.AsyncClient() as client:
        with pytest.raises(FetchFailed, match='exceeds'):
            await fetch_allowed_page(client, AllowedPolicy(), 'https://darglobal.co.uk/',
                                     'darglobal', engine='scrapling', size_limit=50)


@pytest.mark.asyncio
async def test_wasalt_permission_gate_precedes_scrapling_import():
    report = await scrape_wasalt(max_pages=1, engine='scrapling')
    assert report.status == 'permission_required'
    assert report.fetched == 0
    assert report.engine == 'scrapling'


def test_engine_validation():
    assert require_engine('scrapling') == 'scrapling'
    with pytest.raises(ValueError):
        require_engine('stealthy')
    with pytest.raises(ValidationError):
        Settings(scraper_engine='bypass')


def test_scrapling_unavailable_reports_blocked_without_network(monkeypatch):
    import app.ingestion.crawler as crawler
    monkeypatch.setattr(crawler, 'validate_official_url', safe_test_url)
    monkeypatch.setattr(crawler, 'scrapling_available', lambda: False)

    import asyncio
    report = asyncio.run(crawler.crawl('darglobal', 'https://darglobal.co.uk/', engine='scrapling'))
    assert report.status == 'unavailable'
    assert report.errors == 1
    assert report.fetched == 0


@pytest.mark.asyncio
async def test_session_pool_reused_and_closed(monkeypatch):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)
    calls = install_fake_scrapling(monkeypatch, FakePage())
    async with httpx.AsyncClient() as client, ScraplingCrawlSession() as session:
        assert calls == []  # no package session until a permitted page is fetched
        for path in ('/project/a', '/project/b'):
            await fetch_allowed_page(client, AllowedPolicy(), 'https://darglobal.co.uk'+path,
                                     'darglobal', engine='scrapling', session=session)
    assert [call[0] for call in calls] == ['open','https://darglobal.co.uk/project/a',
                                          'https://darglobal.co.uk/project/b','close']
    assert calls[0][1]['impersonate'] is None
    assert calls[0][1]['verify'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('engine', ['httpx','scrapling'])
async def test_cloudflare_challenge_never_returned_as_evidence(monkeypatch, engine):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)
    class ChallengePage(FakePage):
        status = 403
        headers = {'Content-Type': 'text/html', 'CF-Mitigated': 'challenge'}
        body = b'<title>Just a moment...</title>'
    page = ChallengePage()
    calls = install_fake_scrapling(monkeypatch, page)
    requests = []
    def response(request):
        requests.append(request)
        return httpx.Response(page.status, headers=page.headers, content=page.body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ChallengeBlocked, match='Cloudflare security challenge'):
            await fetch_allowed_page(client, AllowedPolicy(), 'https://darglobal.co.uk/',
                                     'darglobal', engine=engine)
    if engine == 'scrapling':
        assert [call[0] for call in calls] == ['open','https://darglobal.co.uk/','close']
        assert not requests
    else:
        assert len(requests) == 1 and not calls


@pytest.mark.asyncio
async def test_challenge_html_with_no_header_is_not_indexable(monkeypatch):
    from app.ingestion import fetchers
    monkeypatch.setattr(fetchers, 'validate_official_url', safe_test_url)
    class ChallengePage(FakePage):
        body = b'<title>Just a moment...</title><script src="https://challenges.cloudflare.com/a"></script>'
    install_fake_scrapling(monkeypatch, ChallengePage())
    async with httpx.AsyncClient() as client:
        with pytest.raises(ChallengeBlocked):
            await fetch_allowed_page(client, AllowedPolicy(), 'https://darglobal.co.uk/',
                                     'darglobal', engine='scrapling')
