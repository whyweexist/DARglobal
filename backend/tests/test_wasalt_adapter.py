"""Offline fixtures only. Actual public site integration must be verified separately."""
import httpx
import pytest
from sqlalchemy import select, func
from app.core.config import settings
from app.db.schema import initialize
from app.db.models import Document, Property
from app.db.session import session_factory
from app.ingestion import wasalt
from app.ingestion.fetchers import FetchedPage
from app.ingestion.parser import parse_html
from app.ingestion.wasalt_site import canonical_url, listing_links, next_page, seed_urls
from app.rag.indexer import upsert_page
from app.rag.retrieval import HybridRetriever
from app.agents import tools

CATEGORY = 'https://wasalt.sa/en/apartments-for-sale-in-riyadh'
DETAIL = 'https://wasalt.sa/en/property/sale/fixture-apartment-123'
PROJECT = 'https://wasalt.sa/en/project/Riyadh/fixture-project-987'
RENT = 'https://wasalt.sa/en/property/rent/fixture-rental-456'
CATALOG_HTML = '''<html lang="en"><title>Riyadh catalogue</title><main>
<h1>Apartments for Sale in Riyadh</h1>
<div><a href="/en/property/sale/fixture-apartment-123?utm_source=test"><span>704,000 Apartment 110 SQM with 2 Bedrooms</span></a><h6>Fixture District, Riyadh</h6></div>
<div><a href="/en/project/Riyadh/fixture-project-987"><span>Fixture Project starting from 1.2M</span></a><h6>Another District, Riyadh</h6></div>
<a href="?page=2&amp;utm_source=test">2</a>
<a href="https://attacker.example/en/property/sale/name">Fake external</a><a href="/en/s/terms-of-use">Terms</a>
</main></html>'''
DETAIL_HTML = '''<html lang="en"><title>Properties for Sale</title><main>
<h1>Fixture Apartment</h1><div>For Sale</div><h2>Property Description</h2>
<p>Apartment for Sale in Fixture District, Riyadh</p><p>Built up Area: 110 SQM</p>
<p>The property has 2 bedrooms and 3 bathrooms.</p><p>Price: 704,000 SAR</p><p>Includes balcony and swimming pool access.</p>
<p>Phone: 0501234567</p><p>FAL License No:</p><p>99922233</p>
<h2>Similar Properties</h2><p>Price: 2,000,000 SAR</p><p>6 bedrooms</p></main></html>'''
PROJECT_HTML = '''<html><title>Fixture Project For Sale</title><main><h1>Fixture Project</h1><p>For Sale</p><h2>About Project</h2>
<p>A development with a communal garden and residents' gym. Apartment types range from two to four bedrooms.</p>
<p>Area 100 - 200 SQM</p><p>Prices start from 1.2M SAR</p><p>Ref no. 987</p>
<h2>Similar Properties</h2><p>Price: 999999 SAR</p></main></html>'''
RENT_HTML = '''<html lang="ar"><title>شقة للإيجار</title><main><h1>شقة للإيجار في جدة</h1><h2>وصف العقار</h2>
<p>شقة للإيجار في جدة بمساحة ١٢٠ متر مربع</p><p>٣ غرف نوم و٢ حمامات</p><p>السعر: ٤٥٬٠٠٠ ريال سعودي سنوي</p></main></html>'''


def authorize(monkeypatch):
    monkeypatch.setenv('WASALT_AUTHORIZED','true')
    monkeypatch.setenv('WASALT_AUTHORIZATION_REFERENCE','Test-only authorization')
    monkeypatch.setenv('CRAWL_DELAY_SECONDS','0.5')
    settings.cache_clear()


def test_category_links_preserve_page_and_strip_tracking():
    links=listing_links(CATALOG_HTML,CATEGORY)
    assert DETAIL in links and 'Fixture District, Riyadh' in links[DETAIL]
    assert PROJECT in links
    assert CATEGORY+'?page=2' in links
    assert next_page(CATEGORY,CATALOG_HTML,3)==CATEGORY+'?page=2'
    assert next_page(CATEGORY,CATALOG_HTML,1) is None
    assert not any('attacker' in x or 'terms' in x for x in links)
    assert canonical_url(CATEGORY+'?page=1') == CATEGORY
    assert canonical_url(CATEGORY+'?page=301') is None
    assert canonical_url('https://wasalt.sa/en/account') is None
    assert canonical_url('https://wasalt.sa:81/en') is None
    assert canonical_url('https://wasalt.sa/en/sale/search?cityId=1') is None
    assert canonical_url('https://wasalt.sa/en/sale/search') is None


def test_query_seeds_target_city_property_and_transaction():
    assert seed_urls('Apartments for sale in Riyadh on Wasalt') == [CATEGORY]
    assert seed_urls('شقة للإيجار في جدة') == ['https://wasalt.sa/en/apartments-for-rent-in-jeddah']
    assert len(seed_urls()) >= 6


def test_detail_extracts_explicit_facts_not_related_prices_or_contacts():
    page=parse_html(DETAIL_HTML,'wasalt',url=DETAIL)
    record=page.facts['properties'][0]
    assert record['offers']=={'price':704000.0,'priceCurrency':'SAR'}
    assert record['numberOfBedrooms']==2 and record['numberOfBathroomsTotal']==3
    assert record['floorSize']['value']==110
    assert record['address']['addressLocality']=='Riyadh'
    assert record['transaction_type']=='sale'
    assert '99922233' not in page.text and '0501234567' not in page.text and '2,000,000' not in page.text
    assert 'swimming pool' in page.text


def test_projects_never_turn_starting_price_or_area_range_into_exact_observation():
    page=parse_html(PROJECT_HTML,'wasalt',url=PROJECT)
    facts=page.facts['properties'][0]
    assert facts['address']['addressLocality']=='Riyadh'
    assert 'offers' not in facts and 'floorSize' not in facts
    assert '999999' not in page.text
    assert '1.2M SAR' in page.text


def test_arabic_numeric_fields_and_rental_period():
    page=parse_html(RENT_HTML,'wasalt',url=RENT)
    facts=page.facts['properties'][0]
    assert page.language=='ar'
    assert facts['offers']['price']==45000
    assert facts['numberOfBedrooms']==3 and facts['floorSize']['value']==120
    assert facts['rental_period']=='سنوي' and facts['transaction_type']=='rent'
    assert facts['address']['addressLocality']=='Jeddah'


def test_category_card_content_is_indexed_but_not_promoted_to_detail_record():
    page=parse_html(CATALOG_HTML,'wasalt',url=CATEGORY)
    assert len(page.sections)==2
    assert page.facts == {}
    assert 'Fixture District, Riyadh' in page.text
    assert DETAIL in page.text
    assert not parse_html('<html><title>Just a moment</title><body>Access blocked</body></html>','wasalt',url=DETAIL).sections


def test_fixture_ingestion_round_trip_and_wasalt_search():
    initialize()
    page=parse_html(DETAIL_HTML,'wasalt',url=DETAIL)
    assert upsert_page('wasalt',DETAIL,page)=='inserted'
    assert upsert_page('wasalt',DETAIL,page)=='skipped'
    with session_factory()() as db:
        row=db.scalars(select(Property)).one()
        assert (row.city,row.price,row.bedrooms,row.currency,row.transaction_type)==('Riyadh',704000,2,'SAR','sale')
        assert db.scalar(select(func.count(Document.id)))==1
    hits,_=HybridRetriever().retrieve('Riyadh apartment price',['wasalt'])
    assert any(h.url==DETAIL and '704000' in h.text for h in hits)


@pytest.mark.asyncio
async def test_specialized_scraper_follows_detail_pages_and_pagination(monkeypatch):
    authorize(monkeypatch)
    initialize()
    calls=[]
    async def fetch(client,policy,url,source,*,engine,session=None):
        calls.append(url)
        assert source=='wasalt'
        return FetchedPage(url,{CATEGORY:CATALOG_HTML,DETAIL:DETAIL_HTML,PROJECT:PROJECT_HTML,CATEGORY+'?page=2':CATALOG_HTML}[url],[],engine)
    async def no_sleep(seconds): pass
    monkeypatch.setattr(wasalt,'fetch_allowed_page',fetch)
    monkeypatch.setattr(wasalt.asyncio,'sleep',no_sleep)
    result=await wasalt.scrape_wasalt(max_pages=4,query='apartments for sale in Riyadh')
    assert calls==[CATEGORY,DETAIL,PROJECT,CATEGORY+'?page=2']
    assert result.fetched==4 and result.inserted==4


@pytest.mark.asyncio
async def test_access_refusal_stops_without_circumvention(monkeypatch):
    authorize(monkeypatch)
    calls=[]
    async def deny(client,policy,url,source,*,engine,session=None):
        calls.append(url)
        req=httpx.Request('GET',url)
        raise httpx.HTTPStatusError('Forbidden',request=req,response=httpx.Response(403,request=req))
    monkeypatch.setattr(wasalt,'fetch_allowed_page',deny)
    result=await wasalt.scrape_wasalt(max_pages=30)
    assert len(calls)==1 and result.status=='unavailable' and result.inserted==0
    assert result.failures[0]['reason']=='HTTP 403'


@pytest.mark.asyncio
async def test_live_wasalt_lookup_uses_relevant_category_before_details(monkeypatch):
    authorize(monkeypatch)
    initialize()
    calls=[]
    async def fetch(client,policy,url,source,*,engine,session=None):
        calls.append(url)
        assert source=='wasalt'
        return FetchedPage(url,CATALOG_HTML if url==CATEGORY else DETAIL_HTML,[],engine)
    async def no_sleep(seconds): pass
    monkeypatch.setattr(tools,'fetch_allowed_page',fetch)
    monkeypatch.setattr(tools.asyncio,'sleep',no_sleep)
    activities=await tools.discover_and_ingest('Wasalt apartments for sale in Riyadh',['wasalt'],max_pages=2)
    assert calls==[CATEGORY,DETAIL]
    assert any(a.found==2 for a in activities)


@pytest.mark.asyncio
async def test_challenge_preserves_authorization_and_stops(monkeypatch):
    from app.ingestion.policy import ChallengeBlocked
    from app.ingestion.jobs import record_ingestion
    from app.db.models import Source
    authorize(monkeypatch)
    initialize()
    calls = []
    async def deny(client, policy, url, source, *, engine, session=None):
        calls.append(url)
        raise ChallengeBlocked('Cloudflare security challenge (HTTP 403)')
    async def no_sleep(seconds): pass
    monkeypatch.setattr(wasalt, 'fetch_allowed_page', deny)
    monkeypatch.setattr(wasalt.asyncio, 'sleep', no_sleep)
    result = await wasalt.scrape_wasalt(max_pages=30)
    assert len(calls) == 1
    assert result.status == 'access_restricted' and result.inserted == 0
    record_ingestion(result)
    with session_factory()() as db:
        assert db.get(Source, 'wasalt').permitted is True
        assert 'Cloudflare' in db.get(Source, 'wasalt').permission_note
