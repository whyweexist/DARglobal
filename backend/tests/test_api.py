from fastapi.testclient import TestClient
from app.main import app


def test_health_and_source_status():
    with TestClient(app) as client:
        live = client.get('/api/v1/health/live')
        assert live.status_code == 200
        assert client.get('/api/v1/health/ready').json()['status'] == 'ready'
        sources = client.get('/api/v1/sources').json()['sources']
        assert {s['id'] for s in sources} == {'darglobal', 'wasalt'}


def test_empty_chat_abstains_without_fabricated_documents():
    with TestClient(app) as client:
        reply = client.post('/api/v1/chat', json={'message': 'Are there any apartments in Riyadh?',
            'source_filter': ['wasalt'], 'allow_live_search': False})
        assert reply.status_code == 200
        value = reply.json()
        assert value['status'] == 'no_evidence'
        assert value['sources'] == []
        assert 'conversation_token' in value
        assert client.get('/api/v1/conversations/' + value['conversation_id']).status_code == 403
        assert client.get('/api/v1/conversations/' + value['conversation_id'], headers={
            'X-Conversation-Token': value['conversation_token']}).status_code == 200
        assert client.delete('/api/v1/conversations/' + value['conversation_id'], headers={
            'X-Conversation-Token': value['conversation_token']}).status_code == 200


def test_bad_chat_rejected():
    with TestClient(app) as client:
        assert client.post('/api/v1/chat', json={'message':'x'}).status_code == 422
        assert client.post('/api/v1/chat', json={'message':'valid question',
            'source_filter':['evil']}).status_code == 422
