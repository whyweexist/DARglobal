from app.db.schema import initialize
from app.ingestion.parser import ExtractedPage, parse_html
from app.rag.chunker import StructureAwareChunker
from app.rag.indexer import upsert_page
from app.rag.retrieval import HybridRetriever, match_expr, significant_tokens
from app.rag.grounding import verified_citations
from app.db.session import session_factory
from app.db.models import Document, Chunk
from sqlalchemy import select, func


def test_structure_aware_chunker_preserves_headings():
    body = ' '.join(['Residences feature terraces overlooking the landmark waterfront.'] * 80)
    chunks = StructureAwareChunker(target=80, maximum=120, overlap=12).chunk([('Residence Amenities', body)])
    assert chunks
    assert all(c.tokens <= 120 for c in chunks)
    assert all(c.heading == 'Residence Amenities' for c in chunks)


def test_parser_retains_structured_fact_source():
    html = '''<html lang="ar"><head><title>Source title</title>
    <script type="application/ld+json">{"@type":"Apartment","name":"Verified unit","numberOfBedrooms":2}</script>
    </head><body><main><h1>Project details</h1><p>This building offers a published residential concept with rooftop terrace access and large windows.</p></main></body></html>'''
    page = parse_html(html, 'darglobal')
    assert page.language == 'ar'
    assert 'terrace' in page.text
    assert page.facts['properties'][0]['name'] == 'Verified unit'


def test_data_roundtrip_and_search():
    initialize()
    page = ExtractedPage(title='Project Arbor - Dubai', sections=[('Property overview',
        'Project Arbor is a documented development in Dubai. The source describes modern residences, '
        'courtyard gardens and a spacious communal lounge for residents. This is test-only fixture text.')])
    assert upsert_page('darglobal', 'https://darglobal.co.uk/projects/arbor', page) == 'inserted'
    assert upsert_page('darglobal', 'https://darglobal.co.uk/projects/arbor', page) == 'skipped'
    with session_factory()() as db:
        assert db.scalar(select(func.count(Document.id))) == 1
        assert db.scalar(select(func.count(Chunk.id))) == 1
    hits, degraded = HybridRetriever().retrieve('Arbor Dubai courtyard gardens', ['darglobal'])
    assert hits and hits[0].title == 'Project Arbor - Dubai'
    assert hits[0].url.startswith('https://')


def test_fts_query_is_quoted():
    assert match_expr('Dubai OR 1234*') == '"dubai" OR "1234"'
    assert significant_tokens('Which buildings are in Dubai?') == ['buildings', 'dubai']


def test_grounding_rejects_invalid_citations_and_numbers():
    from app.rag.retrieval import Evidence
    ev = Evidence(chunk_id=1, title='Source', source='darglobal', url='https://darglobal.co.uk',
                  text='Price is 1200 AED and the project is in Dubai.', fetched_at='2026-11-18', score=1.0)
    assert verified_citations('Price is 1200 AED [E1]', [ev])[0]
    assert not verified_citations('Price is 999999 AED [E1]', [ev])[0]
    assert not verified_citations('A claim [E22]', [ev])[0]
