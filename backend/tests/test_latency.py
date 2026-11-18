"""Latency and provider-choice regressions, with isolated test-only doubles."""
import asyncio
import json
from threading import Barrier

import httpx
import numpy as np
import pytest

from app.core.config import Settings, settings
from app.rag.retrieval import Evidence


def evidence():
    return Evidence(1, 'Test project', 'darglobal', 'https://darglobal.co.uk/test',
                    'Test project has a swimming pool. Price is AED 1200.', '2025-01-01', 1)


def test_wasalt_default_is_independent_of_global_engine(monkeypatch):
    for name in ('WASALT_ENGINE','APIFY_ENABLED','APIFY_LIVE_SEARCH'):
        monkeypatch.delenv(name, raising=False)
    cfg = Settings(_env_file=None, scraper_engine='scrapling')
    assert cfg.effective_wasalt_engine == 'httpx'
    assert not cfg.apify_enabled and not cfg.apify_live_search
    assert Settings(_env_file=None, scraper_engine='scrapling', wasalt_engine='inherit').effective_wasalt_engine == 'scrapling'
    assert Settings(_env_file=None, wasalt_engine='apify').effective_wasalt_engine == 'apify'


@pytest.mark.asyncio
async def test_default_route_does_not_wait_for_catalog(monkeypatch):
    from app.llm import gateway
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only'); settings.cache_clear()
    async def no_catalog(*a, **kw): pytest.fail('Healthy default route needs no model catalog fetch')
    monkeypatch.setattr(gateway.registry,'options',no_catalog)
    base = httpx.AsyncClient
    def respond(req):
        assert json.loads(req.content)['model'] == 'openrouter/free'
        return httpx.Response(200, json={'model':'test/free','choices':[{'message':{'content':'Price is AED 1200 [E1]'}}]})
    monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kw:base(transport=httpx.MockTransport(respond),**kw))
    result=await gateway.grounded_answer('Price?', [evidence()], 'openrouter/free')
    assert result['status']=='answered' and not result['fallback_used']


@pytest.mark.asyncio
async def test_lazy_catalog_still_allows_free_fallback(monkeypatch):
    from app.llm import gateway
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only'); settings.cache_clear()
    calls=[]
    async def catalog(*a,**kw):
        calls.append('catalog'); return {'models':[{'id':'other/fixture:free'}]}
    monkeypatch.setattr(gateway.registry,'options',catalog)
    base=httpx.AsyncClient
    def respond(req):
        chosen=json.loads(req.content)['model']; calls.append(chosen)
        if chosen=='openrouter/free': return httpx.Response(503)
        return httpx.Response(200,json={'model':chosen,'choices':[{'message':{'content':'Price is AED 1200 [E1]'}}]})
    monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kw:base(transport=httpx.MockTransport(respond),**kw))
    result=await gateway.grounded_answer('Price?', [evidence()], 'openrouter/free')
    assert calls==['openrouter/free','catalog','other/fixture:free']
    assert result['fallback_used'] and result['status']=='answered'


def test_retrieval_branches_run_concurrently_and_preserve_order(monkeypatch):
    from app.rag import retrieval
    barrier=Barrier(3,timeout=3)
    def branch(*args,**kwargs):
        barrier.wait(); return [evidence()]
    for name in ('lexical_search','semantic_search','structured_search'):
        monkeypatch.setattr(retrieval,name,branch)
    monkeypatch.setattr(retrieval,'constrained_urls',lambda *args:None)
    hits,issues=retrieval.HybridRetriever().retrieve('Test project swimming pool',['darglobal'])
    assert not issues and len(hits)==1 and hits[0].chunk_id==1


def test_query_embeddings_cached_not_answer_or_search_results(monkeypatch):
    from app.rag import embeddings
    calls=[]
    def encode(values):
        calls.extend(values);return [np.zeros(settings().embedding_dim,dtype=np.float32)]
    monkeypatch.setattr(embeddings,'encode',encode)
    embeddings._query_bytes.cache_clear()
    try:
        assert embeddings.query_embedding('Exact query') == embeddings.query_embedding('Exact query')
        embeddings.query_embedding('Different query')
        assert calls==['Exact query','Different query']
        monkeypatch.setenv('EMBEDDING_MODEL','test-second-model');settings.cache_clear()
        embeddings.query_embedding('Exact query')
        assert calls[-1]=='Exact query' and len(calls)==3
    finally:
        embeddings._query_bytes.cache_clear()


@pytest.mark.asyncio
async def test_unchanged_evidence_does_not_trigger_second_generation(monkeypatch):
    from app.agents import orchestrator,tools
    monkeypatch.setenv('RAG_LIVE_SEARCH','true');settings.cache_clear()
    calls=[]
    async def answer(*args,**kwargs):
        calls.append('generation');return {'status':'insufficient_evidence','answer':'not enough evidence','sources':[]}
    async def live(*args,**kwargs):
        calls.append('live');return [tools.SearchActivity('discover','completed','No change')]
    service=orchestrator.RAGOrchestrator()
    monkeypatch.setattr(service.retriever,'retrieve',lambda *a:([evidence()],[]))
    monkeypatch.setattr(orchestrator,'grounded_answer',answer)
    monkeypatch.setattr(orchestrator,'discover_and_ingest',live)
    result=await service.answer('Test project swimming pool','openrouter/free',['darglobal'])
    assert calls==['generation','live']
    assert set(result['timings_ms'])=={'retrieval_ms','live_search_ms','generation_ms','total_ms'}


@pytest.mark.asyncio
async def test_cooldown_skips_recent_access_refusal_not_provider_switch(monkeypatch):
    from app.agents import tools
    monkeypatch.setenv('WASALT_AUTHORIZED','true');monkeypatch.setenv('WASALT_AUTHORIZATION_REFERENCE','test-only');settings.cache_clear()
    calls=[]
    async def forbidden(client,policy,url,source,**kwargs):
        calls.append(url);req=httpx.Request('GET',url)
        raise httpx.HTTPStatusError('Forbidden',request=req,response=httpx.Response(403,request=req))
    monkeypatch.setattr(tools,'fetch_allowed_page',forbidden)
    first=await tools.discover_and_ingest('Wasalt Riyadh',['wasalt'])
    assert any('HTTP 403' in a.detail for a in first)
    second=await tools.discover_and_ingest('Wasalt Jeddah',['wasalt'])
    assert len(calls)==1 and second[0].status=='access_cooldown'
