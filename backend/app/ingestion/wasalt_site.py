"""Wasalt public-page adapter. No private endpoints or browser evasion.

Route patterns are based on the public English catalogue and detail pages.
Only a bounded page parameter is retained on category pages.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup, Tag

BASE = 'https://wasalt.sa'
HOSTS = {'wasalt.sa', 'www.wasalt.sa'}
CITIES = {'riyadh': 'Riyadh', 'jeddah': 'Jeddah', 'makkah': 'Makkah',
          'madinah': 'Madinah', 'dammam': 'Dammam', 'al-khobar': 'Al Khobar',
          'saudi-arabia': 'Saudi Arabia'}
ARABIC_CITIES = {'الرياض': 'riyadh', 'جدة': 'jeddah', 'مكة': 'makkah', 'المدينة': 'madinah', 'الدمام': 'dammam', 'الخبر': 'al-khobar'}
CATEGORY = re.compile(r'^/en/(?:properties|apartments|villas|lands|buildings|floors|furnished-apartments|rest-houses|offices|shops|warehouses)-for-(?:sale|rent)-in-[a-z0-9-]+/?$', re.I)
DETAIL = re.compile(r'^/en/(?:property/(?:sale|rent)/[^/]+|project/[^/]+/[^/]+)/?$', re.I)


def kind(url: str) -> str:
    path = urlsplit(url).path.rstrip('/')
    if DETAIL.fullmatch(path):
        return 'detail'
    if CATEGORY.fullmatch(path):
        return 'category'
    if path in ('', '/en'):
        return 'home'
    return ''


def canonical_url(url: str, base: str = BASE) -> str | None:
    try:
        p = urlsplit(urljoin(base, url))
        if p.scheme != 'https' or p.hostname not in HOSTS or p.port not in (None, 443) or p.username or p.password:
            return None
        path = p.path.rstrip('/') or '/'
        # Keep case in project slugs; discard tracking parameters and fragments.
        target = urlunsplit(('https', p.hostname, path, '', ''))
        role = kind(target)
        if not role:
            return None
        query = dict(parse_qsl(p.query, keep_blank_values=False, max_num_fields=30))
        if role == 'category' and 'page' in query:
            page = query['page']
            if not page.isascii() or not page.isdigit() or not 1 <= int(page) <= 300:
                return None
            if int(page) > 1:
                target += '?' + urlencode({'page': int(page)})
        return target
    except ValueError:
        return None


def seed_urls(query: str = '') -> list[str]:
    q = query.casefold()
    for ar, city in ARABIC_CITIES.items():
        q = q.replace(ar, city)
    if query:
        cities = [city for city, name in CITIES.items() if city in q or name.casefold() in q]
        cities = cities or ['saudi-arabia']
        prop = next((plural for words, plural in [(('apartment','flat','شقة','شقق'), 'apartments'), (('villa','فيلا','فلل'), 'villas'), (('land','أرض','أراضي'), 'lands'), (('building','عمارة'), 'buildings')] if any(w in q for w in words)), 'properties')
        modes = ['rent'] if any(w in q for w in ('rent','lease','إيجار','ايجار')) else ['sale'] if any(w in q for w in ('sale','buy','purchase','بيع')) else ['sale','rent']
        return [f'{BASE}/en/{prop}-for-{mode}-in-{city}' for city in cities[:2] for mode in modes]
    # Deliberately spread crawl budget across cities and transaction types.
    return [f'{BASE}/en/properties-for-{mode}-in-{city}' for city, mode in [('riyadh','sale'), ('jeddah','rent'), ('riyadh','rent'), ('jeddah','sale'), ('dammam','sale'), ('makkah','sale'), ('madinah','sale'), ('saudi-arabia','sale')]]


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def listing_links(html: str, base: str) -> dict[str, str]:
    """Read actual visible links, including cards that use div/span elements."""
    soup = BeautifulSoup(html, 'lxml')
    output: dict[str, str] = {}
    for a in soup.find_all('a', href=True, limit=1000):
        url = canonical_url(str(a['href']), base)
        if not url or url == canonical_url(base):
            continue
        label = clean(a.get_text(' ', strip=True)) or clean(str(a.get('aria-label', '')))
        if kind(url) == 'detail':
            # Location is often a sibling h6 in the same card. Never borrow it
            # from a container with a second different property link.
            for parent in list(a.parents)[:4]:
                if not isinstance(parent, Tag) or parent.name in ('main','body','html'):
                    break
                refs = {canonical_url(str(x['href']), base) for x in parent.find_all('a', href=True, limit=25)}
                if any(u and kind(u)=='detail' and u!=url for u in refs):
                    break
                loc = parent.find('h6')
                if loc:
                    location = clean(loc.get_text(' ', strip=True))
                    if location and location not in label:
                        label = f'{label} | {location}'
                    break
        if label or kind(url) in ('detail','category'):
            if len(label) > len(output.get(url,'')) or url not in output:
                output[url] = label[:600]
    return output


def next_page(url: str, html: str, maximum: int) -> str | None:
    """Follow advertised page links only; allow at most configured page number."""
    if kind(url) != 'category':
        return None
    current = int(dict(parse_qsl(urlsplit(url).query)).get('page','1'))
    if current >= maximum:
        return None
    path = urlsplit(url).path.rstrip('/')
    wanted = current + 1
    links = listing_links(html, url)
    for u in links:
        if urlsplit(u).path.rstrip('/') == path and dict(parse_qsl(urlsplit(u).query)).get('page') == str(wanted):
            return u
    # Some server-rendered catalogues use numeric buttons rather than anchors.
    # A numeric pagination button is evidence that the page number exists.
    soup = BeautifulSoup(html, 'lxml')
    for element in soup.select('[aria-label], [class*="pagination" i], [class*="Pagination"]'):
        attr = str(element.get('aria-label','')).casefold()
        classes = ' '.join(element.get('class',[])).casefold()
        if 'pagination' not in attr and 'pagination' not in classes:
            continue
        if any(clean(b.get_text(' ',strip=True)) == str(wanted) for b in element.select('button, a')):
            return urlunsplit(('https', urlsplit(url).netloc, path, f'page={wanted}', ''))
    return None
