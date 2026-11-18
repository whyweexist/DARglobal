"""Contract fixtures only, never shipped into the app database."""
import json
from datetime import datetime, timezone
import httpx
import pytest
from sqlalchemy import select
from app.core.config import settings
from app.db.schema import initialize
from app.db.models import Document, Property
from app.db.session import session_factory
from app.ingestion import apify_wasalt as apify
from app.ingestion.wasalt import scrape_wasalt
from app.rag.retrieval import HybridRetriever


def configure(monkeypatch):
    for k,v in {'WASALT_AUTHORIZED':'true','WASALT_AUTHORIZATION_REFERENCE':'test-only permission',
                'WASALT_ENGINE':'apify','APIFY_ENABLED':'true','APIFY_TOKEN':'test-only-key','APIFY_MAX_RUNS_PER_DAY':'2'}.items():
        monkeypatch.setenv(k,v)
    settings.cache_clear();initialize()


def fixture_row(**kwargs):
    return {'platform':'wasalt','source_url':'https://wasalt.sa/en/property/sale/test-contract-123',
            'fetched_at':'2025-01-03T10:00:00Z','title_en':'Contract fixture apartment Riyadh',
            'city_en':'Riyadh','district_en':'Test District','property_type':'apartment', 'listing_type':'sale',
            'price_sar':750000,'area_sqm':120,'bedrooms':2,'bathrooms':3,'amenities':['Swimming pool','Parking'],
            'description_en':'Test-only description of a quiet residential unit. Contact +966 501234567.',
            'agent_phone':'0505555555','agent_email':'private@example.com',**kwargs}


def test_documented_actor_input_and_price_decimal():
    data=apify.actor_input('Wasalt apartments for sale in Riyadh under 1.5 million SAR with 2 bedrooms',10)
    assert data['platforms']==['wasalt'] and data['useProxy'] is False
    assert data['cities']==['Riyadh'] and data['categories']==['apartment']
    assert data['listingType']=='sale' and data['maxListingsPerPlatform']==10
    assert data['priceMaxSar']==1500000 and data['bedroomsMin']==2
    assert apify.actor_input('فلل للإيجار في جدة',5)['listingType']=='rent'


def test_normalization_whitelist_privacy_and_provenance():
    row=fixture_row();url,page,observed=apify.normalize(row)
    assert url==row['source_url'] and observed==datetime(2025,1,3,10,tzinfo=timezone.utc)
    assert '750000 SAR' in page.text and 'Swimming pool' in page.text
    assert '0505555555' not in page.text and 'private@example.com' not in str(page.facts)
    assert '501234567' not in page.text
    assert apify.normalize(fixture_row(platform='aqar')) is None
    assert apify.normalize(fixture_row(source_url='https://other.example/listing')) is None
    assert apify.normalize(fixture_row(source_url='https://wasalt.sa/search')) is None
    missing=apify.normalize(fixture_row(price_sar=0,description_en=None))[1]
    assert 'Price: 0 SAR' not in missing.text and missing.facts['properties'][0]['offers']['price'] is None


@pytest.mark.asyncio
async def test_apify_disabled_dry_run_and_live_opt_in(monkeypatch):
    configure(monkeypatch)
    async def not_called(*args,**kwargs): pytest.fail('No paid run is allowed')
    monkeypatch.setattr(apify,'fetch_items',not_called)
    assert (await scrape_wasalt(dry_run=True)).status=='dry_run'
    assert (await apify.scrape_apify(live=True)).status=='unavailable'
    monkeypatch.setenv('APIFY_ENABLED','false');settings.cache_clear()
    assert (await scrape_wasalt()).status=='unavailable'


@pytest.mark.asyncio
async def test_actor_http_contract_and_persistence(monkeypatch):
    configure(monkeypatch)
    calls=[]; original=httpx.AsyncClient
    def respond(req):
        calls.append((req.method,req.url.path))
        assert req.url.host=='api.apify.com' and req.headers['authorization']=='Bearer test-only-key'
        if req.method=='POST':
            assert req.url.path.endswith('/actors/constructive_calm~saudi-real-estate-scraper/runs')
            assert req.url.params['maxTotalChargeUsd']=='0.25'
            assert json.loads(req.content)['platforms']==['wasalt']
            return httpx.Response(201,json={'data':{'id':'run1','status':'SUCCEEDED','defaultDatasetId':'dataset1'}})
        assert req.url.path.endswith('/datasets/dataset1/items')
        return httpx.Response(200,json=[fixture_row(),fixture_row(platform='aqar'),{'type':'SUMMARY'}])
    monkeypatch.setattr(apify.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    report=await scrape_wasalt(max_pages=3)
    assert report.status=='complete' and report.inserted==1 and report.fetched==1
    with session_factory()() as db:
        p=db.scalars(select(Property)).one();d=db.scalars(select(Document)).one()
        assert p.price==750000 and p.bedrooms==2 and p.facts['district']=='Test District'
        assert d.method=='authorized_apify' and d.fetched_at.year==2025 and p.observed_at.year==2025
    assert (await scrape_wasalt(max_pages=3)).skipped==1
    assert (await scrape_wasalt(max_pages=3)).detail=='Apify daily run limit reached'
    assert len(calls)==4


@pytest.mark.asyncio
async def test_retrieval_filters_apply_across_branches(monkeypatch):
    configure(monkeypatch)
    from app.rag.indexer import upsert_page
    for row in [fixture_row(),fixture_row(source_url='https://wasalt.sa/en/property/sale/test-other-456',price_sar=2000000,bedrooms=4)]:
        url,page,observed=apify.normalize(row);upsert_page('wasalt',url,page,'authorized_apify',observed_at=observed)
    hits,_=HybridRetriever().retrieve('Show Wasalt apartments for sale in Riyadh with 2 bedrooms under 1 million SAR',['wasalt'])
    assert hits and all(h.url.endswith('test-contract-123') for h in hits)
    hits,_=HybridRetriever().retrieve('Wasalt apartments for sale in Riyadh with 7 bedrooms',['wasalt'])
    assert not hits


@pytest.mark.asyncio
async def test_agent_uses_configured_actor_not_direct_fetch(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv('APIFY_LIVE_SEARCH','true');settings.cache_clear()
    from app.agents import tools
    async def run(*args,**kwargs): return [fixture_row()],'test_run'
    async def forbidden(*args,**kwargs): pytest.fail('Apify selection must not perform a direct site fetch')
    monkeypatch.setattr(apify,'fetch_items',run);monkeypatch.setattr(tools,'fetch_allowed_page',forbidden)
    activities=await tools.discover_and_ingest('Wasalt apartments in Riyadh',['wasalt'])
    assert activities[0].tool=='apify_wasalt' and activities[0].found==1
