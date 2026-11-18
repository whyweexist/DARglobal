"""Approved third-party Wasalt feed. No contact data, proxies or direct challenge bypass.
Actor runs are opt-in, cost-capped and quota-reserved in SQLite before submission.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import math
import re
from urllib.parse import urlsplit, urlunsplit, unquote
import httpx
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine
from app.ingestion.crawler import CrawlReport
from app.ingestion.parser import ExtractedPage
from app.ingestion.policy import assert_source_authorized, PolicyDenied
from app.rag.indexer import upsert_page

ACTOR = 'constructive_calm~saudi-real-estate-scraper'
BASE = 'https://api.apify.com/v2/'
TERMINAL = {'SUCCEEDED','FAILED','ABORTED','TIMED-OUT'}


def safe_text(value, limit=500):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?966|00966|0)\s*5(?:[\s.-]*\d){8}', '[contact removed]', value)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def numeric(value):
    if isinstance(value, bool) or not isinstance(value,(int,float)):
        return None
    return (int(value) if float(value).is_integer() else value) if 0 <= value <= 10**15 and math.isfinite(value) else None


def listing_url(value):
    if not isinstance(value,str):
        return None
    try:
        p=urlsplit(value)
        path=unquote(p.path).casefold()
        if (p.scheme!='https' or p.hostname not in {'wasalt.sa','www.wasalt.sa'} or p.port not in (443,None)
            or p.username or p.password or any(x in path.split('/') for x in ('search','profile','account','login'))
            or not p.path.strip('/')):
            return None
        # The actor is a data source, never a URL-fetching tool. Reject known non-listing routes.
        if any(part in path.split('/') for part in ('blog','contact','terms','privacy','robots.txt','llms.txt')): return None
        return urlunsplit(('https','wasalt.sa',p.path.rstrip('/'),'',''))
    except ValueError:
        return None


def actor_input(query: str, limit: int) -> dict:
    from app.rag.property_query import parse_market_query
    f=parse_market_query(query)
    data={'platforms':['wasalt'],'cities':f['cities'],'categories':f['categories'],
          'listingType':f['transaction'] or 'all','maxListingsPerPlatform':limit,
          'useProxy':False,'fetchBayutRegaDetails':False}
    if f['bedrooms'] is not None: data['bedroomsMin']=f['bedrooms']
    if f['currency'] in (None,'SAR'):
        if 'maximum' in f: data['priceMaxSar']=math.ceil(f['maximum'])
        if 'minimum' in f: data['priceMinSar']=math.floor(f['minimum'])
    return data


def normalize(row: dict) -> tuple[str, ExtractedPage, datetime] | None:
    if row.get('platform')!='wasalt': return None
    url=listing_url(row.get('source_url'))
    if not url: return None
    title=safe_text(row.get('title_en')) or safe_text(row.get('title_ar'))
    if not title: return None
    try:
        observed=datetime.fromisoformat(str(row['fetched_at']).replace('Z','+00:00'))
        if observed.tzinfo is None or observed > datetime.now(timezone.utc): return None
        observed=observed.astimezone(timezone.utc)
    except (KeyError,ValueError,TypeError): return None
    city=safe_text(row.get('city_en')) or safe_text(row.get('city_ar'))
    if city.casefold() in ('khobar','al khobar'): city='Al Khobar'
    district=safe_text(row.get('district_en')) or safe_text(row.get('district_ar'))
    kind=safe_text(row.get('property_type'),100); transaction=safe_text(row.get('listing_type'),30)
    period=safe_text(row.get('rent_period'),30)
    price=numeric(row.get('price_sar')); price=price if price and price>0 else None
    area=numeric(row.get('area_sqm')); beds=numeric(row.get('bedrooms')); baths=numeric(row.get('bathrooms'))
    facts=[('City',city),('District',district),('Property type',kind),('Listing type',transaction),('Arabic city',safe_text(row.get('city_ar'))),('Arabic district',safe_text(row.get('district_ar'))),('Arabic title',safe_text(row.get('title_ar'))),('Price',f'{price} SAR' if price is not None else ''),('Rental period',period),('Area',f'{area} sqm' if area is not None else ''),('Bedrooms',beds),('Bathrooms',baths)]
    details=[f'{label}: {value}' for label,value in facts if value not in ('',None)]
    sections=[(f'{title} — listing facts', '\n'.join(details + ['Source: Wasalt.sa (authorized Apify feed)']))]
    more=[]
    for field,label in [('completion_status','Completion status'),('posted_at','Posted at'),('updated_at','Listing updated at'),('refreshed_at','Refreshed at'),('quality_flags','Data quality flags')]:
        v=row.get(field)
        if isinstance(v,list): v=', '.join(safe_text(x,100) for x in v[:20] if isinstance(x,str))
        v=safe_text(v)
        if v: more.append(f'{label}: {v}')
    for field,label,suffix in [('plot_area_sqm','Plot area',' sqm'),('living_rooms','Living rooms',''),('price_per_sqm_sar','Reported price per square meter',' SAR/sqm')]:
        n=numeric(row.get(field))
        if n is not None and (n>0 or field=='living_rooms'): more.append(f'{label}: {n}{suffix}')
    if isinstance(row.get('is_rega_verified'),bool): more.append('REGA verified (provider flag): '+('yes' if row['is_rega_verified'] else 'no'))
    if isinstance(row.get('furnished'),bool): more.append('Furnished: '+('yes' if row['furnished'] else 'no'))
    if isinstance(row.get('amenities'),list):
        amenities=[safe_text(a,150) for a in row['amenities'][:80] if isinstance(a,str)]
        if any(amenities): more.append('Amenities: '+', '.join(filter(None,amenities)))
    if more: sections.append((f'{title} — amenities and listing status','\n'.join(more)))
    if not any(safe_text(row.get(f)) for f in ('description_en','description_ar')):
        sections.append((f'{title} — source coverage','No full listing description supplied by this data provider. Do not infer additional specifications.'))
    for field in ('description_en','description_ar'):
        description=safe_text(row.get(field),12000)
        if description: sections.append((f'{title} — published description', description))
    prop={'name':title,'@type':kind or 'Property','address':{'addressLocality':city,'addressCountry':'SA'},'transaction_type':transaction,'offers':{'price':price,'priceCurrency':'SAR' if price is not None else None},'floorSize':{'value':area},'numberOfBedrooms':beds,'numberOfBathroomsTotal':baths,'extraction_method':'authorized_apify','rental_period':period,'district':district,'amenities': [safe_text(a,150) for a in row.get('amenities',[])[:80] if isinstance(a,str)] if isinstance(row.get('amenities'),list) else [],'quality_flags':[safe_text(a,100) for a in row.get('quality_flags',[])[:20] if isinstance(a,str)] if isinstance(row.get('quality_flags'),list) else []}
    return url, ExtractedPage(title,sections,'en' if row.get('title_en') else 'ar',{'properties':[prop]}),observed


def reserve_run() -> bool:
    cfg=settings(); day=datetime.now(timezone.utc).date().isoformat()
    with engine().begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS apify_daily_runs(day TEXT PRIMARY KEY, count INTEGER NOT NULL)'))
        result=conn.execute(text('INSERT INTO apify_daily_runs(day,count) VALUES (:day,1) ON CONFLICT(day) DO UPDATE SET count=count+1 WHERE count < :cap'),{'day':day,'cap':cfg.apify_max_runs_per_day})
        return result.rowcount==1


async def fetch_items(query: str, limit: int, *, timeout: int) -> tuple[list, str]:
    cfg=settings()
    if not reserve_run(): raise RuntimeError('Apify daily run limit reached')
    async with httpx.AsyncClient(base_url=BASE, headers={'Authorization':f'Bearer {cfg.apify_token}'},follow_redirects=False,trust_env=False,timeout=15) as client:
        run_id=None
        try:
            async with asyncio.timeout(timeout+8):
                response=await client.post(f'actors/{ACTOR}/runs',json=actor_input(query,limit),params={'timeout':timeout,'maxTotalChargeUsd':cfg.apify_max_charge_usd})
                response.raise_for_status(); run=response.json()['data']; run_id=run['id']
                if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id): raise ValueError('Invalid Apify run ID')
                while run.get('status') not in TERMINAL:
                    await asyncio.sleep(2)
                    response=await client.get(f'actor-runs/{run_id}'); response.raise_for_status(); run=response.json()['data']
                if run.get('status')!='SUCCEEDED': raise RuntimeError('Apify run ended: '+str(run.get('status')))
                dataset=run.get('defaultDatasetId','')
                if not re.fullmatch(r'[A-Za-z0-9_-]+',dataset): raise ValueError('Missing Apify dataset ID')
                async with client.stream('GET',f'datasets/{dataset}/items',params={'format':'json','clean':'true','limit':limit+1}) as response:
                    response.raise_for_status(); buf=bytearray()
                    async for block in response.aiter_bytes():
                        buf.extend(block)
                        if len(buf)>10_000_000: raise ValueError('Apify dataset response exceeds limit')
                import json
                items=json.loads(buf)
                if not isinstance(items,list): raise ValueError('Invalid Apify dataset')
                return items,run_id
        except (TimeoutError,asyncio.CancelledError):
            if run_id:
                try: await asyncio.wait_for(client.post(f'actor-runs/{run_id}/abort'),5)
                except (httpx.HTTPError,TimeoutError): pass
            raise


async def scrape_apify(*, max_pages: int | None=None, dry_run=False, query='', live=False) -> CrawlReport:
    cfg=settings(); report=CrawlReport(source='wasalt',engine='apify')
    try: assert_source_authorized('wasalt')
    except PolicyDenied as exc:
        report.status='permission_required'; report.detail=str(exc); return report
    if max_pages is not None and not 1 <= max_pages <= 250: raise ValueError('max_pages must be between 1 and 250')
    limit=min(max_pages or cfg.apify_max_listings,cfg.apify_max_listings)
    if live: limit=min(limit,cfg.apify_live_max_listings)
    if dry_run:
        report.status='dry_run'; report.detail='No actor run or charge; '+str(actor_input(query,limit)); return report
    if not cfg.apify_enabled or not cfg.apify_token or (live and not cfg.apify_live_search):
        report.status='unavailable'; report.detail='Apify requires APIFY_ENABLED, APIFY_TOKEN and explicit live-search opt-in for chat-triggered runs'; return report
    try:
        items,run_id=await fetch_items(query,limit,timeout=min(cfg.apify_timeout_seconds,max(5,cfg.agent_max_seconds-12)) if live else cfg.apify_timeout_seconds)
        report.detail=f'Apify run {run_id}; public Wasalt fields only'
        for row in items:
            if report.fetched>=limit: break
            if not isinstance(row,dict) or row.get('platform')!='wasalt': continue
            report.fetched+=1
            parsed=normalize(row)
            if not parsed:
                report.errors+=1; report.failures.append({'url':'Wasalt dataset row','reason':'Missing or invalid official listing URL, title or observation time'}); continue
            url,page,observed=parsed
            outcome=await asyncio.to_thread(upsert_page,'wasalt',url,page,'authorized_apify',observed_at=observed)
            setattr(report,outcome,getattr(report,outcome)+1); report.urls.append(url)
        if not report.urls: report.status='unavailable'; report.detail+='; no usable listing records'
        elif report.errors: report.status='partial'
    except httpx.HTTPStatusError as exc:
        report.status='unavailable'; report.errors+=1; report.detail=f'Apify API HTTP {exc.response.status_code}; check token, plan and billing limits'
    except (httpx.HTTPError,TimeoutError,ValueError,KeyError,TypeError,AttributeError,RuntimeError) as exc:
        report.status='unavailable'; report.errors+=1; report.detail=str(exc) if isinstance(exc,RuntimeError) else f'Apify request failed: {type(exc).__name__}'
    return report
