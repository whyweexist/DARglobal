"""Conservative, shared marketplace constraint parsing for SQL and Apify."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from app.ingestion.wasalt_site import CITIES, ARABIC_CITIES

CATEGORIES = {
    'apartment':r'\bapartments?\b|شقق|شقة', 'villa':r'\bvillas?\b|فلل|فيلا',
    'land':r'\b(?:lands?|plots?)\b|أراض|أرض', 'office':r'\boffices?\b|مكتب',
    'commercial':r'\bcommercial\b|تجاري', 'townhouse':r'\btownhouses?\b',
    'shop':r'\bshops?\b|محلات', 'building':r'\bbuildings?\b|عمارة',
}
DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')


def parse_market_query(query: str) -> dict:
    q=query.casefold().translate(DIGITS)
    cities=[name for slug,name in CITIES.items() if slug!='saudi-arabia' and (slug.replace('-',' ') in q or slug in q)]
    # Common spelling in the actor output is Khobar rather than Al Khobar.
    if re.search(r'\bkhobar\b',q) and 'Al Khobar' not in cities: cities.append('Al Khobar')
    cities += [CITIES[slug] for ar,slug in ARABIC_CITIES.items() if ar in q and CITIES[slug] not in cities]
    categories=[k for k,p in CATEGORIES.items() if re.search(p,q)]
    rent=bool(re.search(r'\b(?:rent|rental|lease)\b|إيجار|للإيجار',q)); sale=bool(re.search(r'\b(?:sale|buy|purchase)\b|للبيع',q))
    transaction='rent' if rent and not sale else 'sale' if sale and not rent else None
    bed=re.search(r'(\d+)\s*[- ]?\s*(?:bedrooms?|beds?|غرف نوم|غرف)',q)
    bedrooms=int(bed[1]) if bed and 0<=int(bed[1])<=20 else None
    currency=re.search(r'\b(sar|aed|usd|eur|gbp|qar|omr)\b|ريال سعودي',q)
    curr=(currency[1] or 'sar').upper() if currency else None
    limits={}
    for key,op in [('maximum',r'under|below|less than|أقل من'),('minimum',r'over|above|more than|أكثر من')]:
        m=re.search(r'(?:'+op+r')\s*(?:sar|aed|usd|eur|gbp|qar|omr|ريال)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|mn|m|k|مليون|ألف)?(?![\w.])',q)
        if not m: continue
        multipliers={None:1,'million':1000000,'mn':1000000,'m':1000000,'مليون':1000000,'thousand':1000,'k':1000,'ألف':1000}
        try:
            v=Decimal(m[1].replace(',',''))*multipliers[m[2]]
            if 0<v<=10**12: limits[key]=int(v) if v==v.to_integral_value() else float(v)
        except (InvalidOperation,ValueError): pass
    return {'cities':cities,'categories':categories,'transaction':transaction,'bedrooms':bedrooms,'currency':curr,**limits}
