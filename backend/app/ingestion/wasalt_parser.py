"""Extract listing-specific visible evidence and structured facts, not contact data."""
from __future__ import annotations
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from app.ingestion.wasalt_site import CITIES, clean, kind, listing_links

NUMBER = r'[0-9٠-٩۰-۹][0-9٠-٩۰-۹,٬]*(?:[.٫][0-9٠-٩۰-۹]+)?'
DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫', '01234567890123456789,.')


def number(value: str) -> float:
    return float(value.translate(DIGITS).replace(',',''))


def take(pattern: str, text: str):
    return re.search(pattern, text, flags=re.I | re.M)


def parse_wasalt(html: str, url: str):
    from app.ingestion.parser import ExtractedPage, jsonld_properties
    soup = BeautifulSoup(html, 'lxml')
    language = str(soup.html.get('lang','en'))[:10] if soup.html else 'en'
    title = clean(soup.title.get_text(' ',strip=True)) if soup.title else ''
    role = kind(url)
    if role in ('category','search','home'):
        h1 = soup.find('h1')
        title = clean(h1.get_text(' ',strip=True)) if h1 else title
        sections = []
        if role != 'home':
            for link, label in listing_links(html,url).items():
                if kind(link) == 'detail' and label and len(label) >= 12:
                    # Cards remain observations on the category page; don't
                    # create a detail document or structured row without fetching it.
                    sections.append((title or 'Wasalt catalogue', f'Listing card: {label}. Detail page: {link}'))
        return ExtractedPage(title or 'Wasalt catalogue', sections[:80], language)
    if role != 'detail':
        return ExtractedPage(title or 'Wasalt', [], language)

    # JSON-LD is used only for a single matching detail page, not arbitrary
    # related listings in the same document. Visible facts below take priority.
    records = jsonld_properties(html)
    for item in soup.select('script, style, nav, footer, header, aside, form, svg, noscript, iframe, button, [role=navigation]'):
        item.decompose()
    root = soup.select_one('main, article, [role=main]') or soup.body or soup
    lines = [clean(x) for x in root.stripped_strings if clean(x)]
    # Isolate actual detail content; never read prices in "Similar Properties".
    stops = ('similar properties','related properties','عقارات مشابهة')
    stop = next((i for i,line in enumerate(lines) if i>8 and line.casefold() in stops),len(lines))
    lines = lines[:stop]
    desc_index = next((i for i,v in enumerate(lines) if v.casefold() in ('property description','about project','وصف العقار','عن المشروع')),None)
    desc_lines = []
    if desc_index is not None:
        for line in lines[desc_index+1:desc_index+65]:
            if re.search(r'(?i)^(?:FAL License|Ref no\.?|REGA Information|Last updated|Units Available|WhatsApp|Call Now|Register Interest|Similar Properties|رقم الترخيص|رقم المرجع|اسم المعلن|واتساب)',line):
                break
            # Do not keep contact/license identifiers or advertiser names.
            if re.search(r'(?i)\b(?:phone|mobile|contact|broker|license|whatsapp)\b|(?:رقم الجوال|اتصل|وسيط|رخصة)',line):
                continue
            if re.search(r'\b(?:\+?966|05)[\s\-]?\d{8,10}\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}',line,re.I):
                continue
            if re.search(r'شركة|\b(?:LLC|Ltd\.?|company)\b',line,re.I) and not re.search(r'amenit|facilit|مرافق',line,re.I):
                continue
            desc_lines.append(line)
    description = '\n'.join(dict.fromkeys(desc_lines))[:6500]
    h1 = root.find('h1')
    og = soup.find('meta', attrs={'property':'og:title'})
    if h1:
        title = clean(h1.get_text(' ',strip=True))
    elif og and og.get('content'):
        title = clean(str(og['content']))
    # The detail page often has a generic HTML title; its first description
    # line explicitly names the property and location.
    if desc_lines and re.search(r'(?i)\b(?:for sale|for rent)\b|للبيع|للإيجار',desc_lines[0]):
        title = desc_lines[0]
    title = (title or 'Wasalt property')[:300]
    path = urlsplit(url).path.casefold()
    transaction = 'rent' if '/property/rent/' in path else 'sale' if '/property/sale/' in path else None
    if transaction is None:
        if any(v.casefold()=='for sale' for v in lines[:65]): transaction='sale'
        elif any(v.casefold()=='for rent' for v in lines[:65]): transaction='rent'
    # Restrict visible numeric extraction to the listing description/title.
    evidence = title + '\n' + description
    city = next((name for slug,name in CITIES.items() if slug!='saudi-arabia' and re.search(r'\b'+re.escape(name)+r'\b', evidence,re.I)),None)
    if city is None:
        for ar,en in [('الرياض','Riyadh'),('جدة','Jeddah'),('مكة','Makkah'),('المدينة','Madinah'),('الدمام','Dammam'),('الخبر','Al Khobar')]:
            if ar in evidence: city=en; break
    # Project URLs explicitly contain the city; never infer unknown city from a linked property.
    if not city and '/project/' in path:
        city = CITIES.get(path.split('/')[3]) if len(path.split('/'))>3 else None
    typ = next((name for rx,name in [(r'\bapartment\b|شقة|شقق','Apartment'),(r'\bvilla\b|فيلا|فلل','House'),(r'\bland\b|أرض','Land'),(r'\bbuilding\b|عمارة','Building')] if re.search(rx,title,re.I)),None)
    fact = {'name': title, '@type': typ or 'RealEstateListing', 'transaction_type': transaction, 'address': {'addressLocality': city, 'addressCountry':'Saudi Arabia'} if city else {}, 'extraction_method':'wasalt_visible_detail'}
    price = take(r'(?:price|rent|السعر|الإيجار)\s*[:：]?\s*('+NUMBER+r')\s*(SAR|ريال(?: سعودي)?)\b',description)
    if price and '/project/' not in path:
        fact['offers'] = {'price':number(price.group(1)),'priceCurrency':'SAR'}
        if transaction == 'rent':
            period = re.search(r'(?i)\b(?:yearly|annually|per year|monthly|per month)\b|سنوي|شهري',description)
            if period: fact['rental_period'] = period.group(0)
    area = take(r'('+NUMBER+r')\s*(?:SQM|m²|م²|متر مربع)\b',evidence)
    if area and not re.search(r'\d\s*[-–]\s*'+NUMBER+r'\s*(?:SQM|m²)',evidence,re.I):
        fact['floorSize']={'value':number(area.group(1)), 'unitCode':'MTK'}
    for key, labels in [('numberOfBedrooms',r'bedrooms?|غرف نوم'),('numberOfBathroomsTotal',r'bathrooms?|حمامات')]:
        match=take(r'(?<![\d,])([0-9٠-٩۰-۹]{1,2})\s*(?:'+labels+r')\b',evidence)
        if match: fact[key]=int(number(match.group(1)))
    # Enrich only from a uniquely named JSON-LD record on the detail page.
    for record in records:
        name = str(record.get('name','')).casefold().strip()
        if not name or name != title.casefold().strip():
            continue
        for key in ('offers','floorSize','numberOfBedrooms','numberOfBathroomsTotal'):
            if key not in fact and key in record: fact[key]=record[key]
        if not city and isinstance(record.get('address'),dict):
            fact['address']={k:record['address'][k] for k in ('addressLocality','addressCountry') if isinstance(record['address'].get(k),str)}
        break
    properties = []
    facts_text = [title]
    if '/project/' in path:
        # Project totals/ranges are not individual listing prices. Keep only
        # the visible, explicitly qualified observation in text.
        for line in lines[:100]:
            if re.match(r'(?i)^(?:starts? from|starting from|ابتداء من|يبدأ من)\s*'+NUMBER,line):
                facts_text.append('Advertised project price qualifier: '+line[:100])
                break
        for index,line in enumerate(lines[:65]):
            if line.casefold() in ('bedrooms','bathrooms','built-up area') and index>0:
                value=lines[index-1]
                if re.fullmatch(r'[\d٠-٩۰-۹,.٬٫\s–-]+(?:SQM|sqm)?',value):
                    facts_text.append(line.capitalize()+': '+value)

    if transaction: facts_text.append('Transaction: '+transaction)
    if fact.get('address',{}).get('addressLocality'): facts_text.append('City: '+fact['address']['addressLocality'])
    if typ: facts_text.append('Property type: '+typ)
    if fact.get('rental_period'): facts_text.append('Rental period: '+fact['rental_period'])
    offers = fact.get('offers')
    if isinstance(offers,dict) and offers.get('price') is not None and offers.get('priceCurrency'):
        facts_text.append(f"Published price: {offers['price']} {offers['priceCurrency']}")
    for k,label in [('numberOfBedrooms','Bedrooms'),('numberOfBathroomsTotal','Bathrooms')]:
        if fact.get(k) is not None: facts_text.append(f'{label}: {fact[k]}')
    size=fact.get('floorSize')
    if isinstance(size,dict) and size.get('value') is not None and size.get('unitCode') in ('MTK','SQM'):
        facts_text.append(f"Area: {size['value']} SQM")
    # A real description or matched structured fields are required; a generic
    # title or challenge page is not a successful ingestion.
    if (description and len(description)>=20) or (len(facts_text)>=4 and (fact.get('offers') or fact.get('floorSize') or fact.get('numberOfBedrooms'))):
        properties.append(fact)
        sections=[('Listing facts', '\n'.join(facts_text))]
        if description: sections.append((title,description))
    else:
        sections=[]
    return ExtractedPage(title, sections, language, {'properties':properties} if properties else {})
