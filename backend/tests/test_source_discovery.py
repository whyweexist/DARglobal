"""Regression tests for catalogue discovery. Synthetic HTML is test-only."""
import pytest
import httpx
from app.core.config import settings
from app.db.schema import initialize
from app.ingestion.crawler import DARGLOBAL_CATALOG, catalog_links
from app.ingestion.parser import parse_html
from app.ingestion.fetchers import FetchedPage
from app.agents.tools import rank_links, discover_and_ingest
from app.rag.retrieval import HybridRetriever

CATALOG = '''<html><head><title>Project catalogue</title></head><body><main>
<h2>Find a property</h2>
<a href="/dg1"><div>Dubai, United Arab Emirates</div><span>DG1</span></a>
<a href="/landing-page/aida"><div>Muscat, Oman</div><span>AIDA</span></a>
<a href="https://other.example/foo">Dubai external listing</a>
</main></body></html>'''


def test_catalogue_labels_support_opaque_urls():
    links = catalog_links(CATALOG, DARGLOBAL_CATALOG, 'darglobal')
    assert rank_links('projects in Dubai', links) == ['https://darglobal.co.uk/dg1']
    assert 'https://other.example/foo' not in links
    parsed = parse_html(CATALOG, 'darglobal', url=DARGLOBAL_CATALOG)
    assert 'Dubai, United Arab Emirates DG1' in parsed.text


@pytest.mark.asyncio
async def test_live_catalogue_discovery_indexes_relevant_record(monkeypatch):
    from app.agents import tools
    initialize()
    monkeypatch.setenv('CRAWL_DELAY_SECONDS', '0.5')
    settings.cache_clear()
    calls = []
    async def fetch(client, policy, url, source, *, engine, session=None):
        calls.append(url)
        html = CATALOG if url == DARGLOBAL_CATALOG else '<title>DG1 Dubai</title><main><h2>Amenities</h2><p>Residents have access to a swimming pool and an indoor gym.</p></main>'
        return FetchedPage(url, html, [], engine)
    monkeypatch.setattr(tools, 'fetch_allowed_page', fetch)
    activities = await discover_and_ingest('DG1 Dubai amenities', ['darglobal','wasalt'], max_pages=2)
    assert calls == [DARGLOBAL_CATALOG, 'https://darglobal.co.uk/dg1']
    assert any(a.status == 'permission_required' for a in activities)
    assert any(a.found == 2 for a in activities)
    hits, _ = HybridRetriever().retrieve('DG1 Dubai amenities',['darglobal'])
    assert any(h.url.endswith('/dg1') and 'swimming pool' in h.text for h in hits)


@pytest.mark.asyncio
async def test_live_fetch_failure_reports_actual_status(monkeypatch):
    from app.agents import tools
    async def denied(client, policy, url, source, *, engine, session=None):
        req = httpx.Request('GET',url)
        raise httpx.HTTPStatusError('Forbidden',request=req,response=httpx.Response(403,request=req))
    monkeypatch.setattr(tools,'fetch_allowed_page',denied)
    activities = await discover_and_ingest('Dubai', ['darglobal'], max_pages=1)
    assert any(a.status == 'fetch_failed' and 'HTTP 403' in a.detail for a in activities)
    assert not any(a.status == 'completed' for a in activities)
