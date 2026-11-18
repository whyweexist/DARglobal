"""Regression fixtures are test-only and never included in the runtime database."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.db.schema import initialize
from app.ingestion.parser import ExtractedPage, parse_html
from app.rag.indexer import upsert_page
from app.rag.retrieval import HybridRetriever, Evidence
from app.rag.grounding import verified_citations, evidence_only
from app.llm.gateway import grounded_answer, interpret_answer
from app.memory.context import plan_query
from app.main import app


def seed():
    initialize()
    repeated = 'At the core of DarGlobal is a disciplined real estate development model. The company describes luxury apartments in Dubai and Qatar and villas in Spain.'
    upsert_page('darglobal','https://darglobal.co.uk/',ExtractedPage('DarGlobal | International Luxury Real Estate Developer',[
        ('Global Real Estate Developments',repeated),('Property portfolio',repeated),('Overview',repeated)]))
    upsert_page('darglobal','https://darglobal.co.uk/projects/test-arbor',ExtractedPage('Test Arbor project Dubai',[
        ('Arbor project amenities','The Arbor project in Dubai has a courtyard garden and a swimming pool for the exclusive use of residents.'),
        ('Arbor project price','The published price for the Arbor project in Dubai is AED 1200000, subject to the conditions stated in the source.')]))
    upsert_page('darglobal','https://darglobal.co.uk/projects/test-linden',ExtractedPage('Test Linden project Oman',[
        ('Linden project amenities','The Linden project in Oman includes a fitness gym and a rooftop terrace for the use of residents.')] ))


def test_distinct_queries_and_unrelated_questions():
    seed(); r = HybridRetriever()
    first,_=r.retrieve('Arbor project Dubai courtyard garden',['darglobal'])
    second,_=r.retrieve('Linden project Oman rooftop terrace',['darglobal'])
    unknown,_=r.retrieve('DarGlobal Mars lunar rocket launch',['darglobal'])
    assert first and first[0].url.endswith('test-arbor')
    assert second and second[0].url.endswith('test-linden')
    assert unknown == []


def test_duplicate_homepage_not_returned_three_times():
    seed(); r=HybridRetriever()
    hits,_=r.retrieve('DarGlobal Dubai',['darglobal'])
    assert len([h for h in hits if h.url=='https://darglobal.co.uk/']) <= 1
    reply=evidence_only(hits,'llm_unconfigured')
    assert 'API key is missing' in reply['answer']
    assert 'disciplined real estate' not in reply['answer']
    assert len({e['url'] for e in reply['sources']})==len(reply['sources'])


def test_parser_removes_duplicate_paragraphs():
    p=parse_html('<main><h1>Property</h1><p>Repeated content about a specific property and its unique design.</p><h2>More</h2><p>Repeated content about a specific property and its unique design.</p></main>','darglobal')
    assert p.text.count('Repeated content') == 1


def test_followups_use_history_but_new_subjects_do_not():
    history=[{'role':'user','content':'Tell me about Arbor in Dubai'}, {'role':'assistant','content':'Test response about Arbor.'}]
    follow=plan_query('What is its price?',history)
    assert 'Arbor' in follow.search_query and 'price' in follow.fields and follow.history
    new=plan_query('Tell me about Linden in Oman',history)
    assert 'Arbor' not in new.search_query and not new.history
    assert not plan_query('What is its price?',[]).history


def test_citation_validation_uses_cited_excerpt_not_other_documents():
    a=Evidence(1,'A','darglobal','https://darglobal.co.uk/a','Price is AED 1200.','today',1)
    b=Evidence(2,'B','darglobal','https://darglobal.co.uk/b','Price is AED 9999.','today',1)
    assert verified_citations('1. The price is AED 1,200 [E1]',[a,b])[0]
    assert not verified_citations('The price is AED 9999 [E1]',[a,b])[0]
    assert not verified_citations('The price is AED 200 [E1]',[a,b])[0]
    result,status=interpret_answer('INSUFFICIENT_EVIDENCE',[a,b])
    assert status=='ok' and result['status']=='insufficient_evidence'


def test_missing_field_abstains_without_a_model_call():
    seed()
    with TestClient(app) as client:
        reply=client.post('/api/v1/chat',json={'message':'What is the completion date of Linden in Oman?','allow_live_search':False}).json()
        assert reply['status'] in {'no_evidence','insufficient_evidence'}
        assert reply['sources']==[]


@pytest.mark.asyncio
async def test_gateway_success_abstention_and_explicit_errors(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only-key'); settings.cache_clear()
    from app.llm import gateway
    from app.llm.registry import registry
    async def options(*args,**kwargs): return {'models':[{'id':'openrouter/free'}]}
    monkeypatch.setattr(registry,'options',options)
    original=httpx.AsyncClient
    calls=[]
    state={'mode':'success'}
    def responder(req):
        calls.append(json.loads(req.content))
        if state['mode']=='auth':return httpx.Response(401,json={'error':{'message':'invalid key'}})
        if state['mode']=='quota':return httpx.Response(429,headers={'retry-after':'60'})
        return httpx.Response(200,json={'model':'fixture/provider:free','choices':[{'message':{'content': 'INSUFFICIENT_EVIDENCE' if state['mode']=='abstain' else 'Price is AED 1200 [E1]'}}]})
    monkeypatch.setattr(gateway.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(responder),**kw))
    evidence=[Evidence(1,'A','darglobal','https://darglobal.co.uk/a','Price is AED 1200.','today',1)]
    history=[{'role':'user','content':'Tell me about A'}]
    response=await grounded_answer('What is its price?',evidence,'openrouter/free',history)
    assert response['status']=='answered' and response['model_used']=='fixture/provider:free'
    body=json.loads(calls[-1]['messages'][1]['content'])
    assert body['question']=='What is its price?' and body['conversation_context_not_evidence']==history
    state['mode']='abstain'; response=await grounded_answer('Unknown?',evidence,'openrouter/free')
    assert response['status']=='insufficient_evidence'
    state['mode']='auth'; response=await grounded_answer('Price?',evidence,'openrouter/free')
    assert response['reason']=='llm_auth_error'
    state['mode']='quota'; response=await grounded_answer('Price?',evidence,'openrouter/free')
    assert response['reason']=='rate_limited'


def test_api_threads_are_isolated_and_followup_context_is_saved(monkeypatch):
    from app.agents.orchestrator import RAGOrchestrator
    seen=[]
    async def answer(self,question,model,sources,allow_live_search=True,on_status=None,history=None):
        seen.append((question,history))
        return {'answer':'Test-only response to '+question,'status':'answered','sources':[]}
    monkeypatch.setattr(RAGOrchestrator,'answer',answer)
    with TestClient(app) as client:
        start=client.post('/api/v1/chat',json={'message':'Tell me about Arbor'}).json()
        second=client.post('/api/v1/chat',json={'message':'What is its price?','conversation_id':start['conversation_id'],'conversation_token':start['conversation_token']}).json()
        new=client.post('/api/v1/chat',json={'message':'Tell me about Linden'}).json()
        assert second['conversation_id']==start['conversation_id']
        assert new['conversation_id']!=start['conversation_id']
        assert seen[0][1]==[] and seen[2][1]==[]
        assert [m['role'] for m in seen[1][1]]==['user','assistant']
        assert seen[2][0]=='Tell me about Linden'


def test_export_actual_records_only(tmp_path):
    from app.local_tools import export_data
    seed(); info=export_data(str(tmp_path/'exports'))
    assert info['rows']['darglobal-documents']==3
    assert info['rows']['wasalt-documents']==0
    assert json.loads((tmp_path/'exports/wasalt-documents.json').read_text())==[]
