"""Native and container CLI operations; export only stored authorized data."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from sqlalchemy import text
from app.db.session import engine
from app.core.config import settings


def stats() -> dict:
    with engine().connect() as conn:
        return {name: conn.execute(text(f'SELECT COUNT(*) FROM {name}')).scalar_one()
                for name in ('sources','documents','chunks','properties','ingestion_runs','conversations')}


def export_data(directory: str) -> dict:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    with engine().connect() as conn:
        for source in ('darglobal','wasalt'):
            for table in ('documents','properties','chunks'):
                if table=='chunks':
                    sql = 'SELECT c.id,c.document_id,c.ordinal,c.heading,c.text,c.tokens,c.embedding_model,d.url,d.source_id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.source_id=:source ORDER BY c.id'
                else:
                    sql = f'SELECT * FROM {table} WHERE source_id=:source ORDER BY id'
                rows = conn.execute(text(sql),{'source':source})
                fields = list(rows.keys())
                records = [dict(row) for row in rows.mappings()]
                key = f'{source}-{table}'
                counts[key] = len(records)
                (out/f'{key}.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
                with (out/f'{key}.csv').open('w',encoding='utf-8',newline='') as f:
                    writer = csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(records)
    return {'directory':str(out),'rows':counts}


async def chat_loop(model: str, source: str, question: str | None, allow_live_search: bool = True):
    from app.agents.orchestrator import RAGOrchestrator
    from app.llm.registry import registry
    await registry.validate(model)
    history = []
    sources = ['darglobal','wasalt'] if source=='all' else [source]
    while True:
        if question is None:
            try:
                user = input('\nYou > ').strip()
            except (EOFError, KeyboardInterrupt):
                break
        else:
            user = question
        if user in {'/exit','/quit'}: break
        if user == '/new':
            history.clear(); print('New conversation'); continue
        if not user:
            if question is not None:
                break
            continue
        result = await RAGOrchestrator().answer(user,model,sources,allow_live_search,history=history)
        print(f"\n{result['answer']}\n\nStatus: {result['status']} | Model: {result.get('model_used') or 'none'}")
        for ev in result['sources']:
            print(f"[{ev['id']}] {ev['title']}: {ev['url']}")
        for activity in result.get('tool_activity',[]):
            print(f"Tool: {activity['status']} – {activity['detail']}")
        history.extend([{'role':'user','content':user},{'role':'assistant','content':result['answer']}]);history = history[-12:]
        if question is not None: break


async def model_catalog():
    from app.llm.registry import registry
    return await registry.options(refresh=True)


async def check_ai(model: str | None = None) -> dict:
    """Make one small free-model request independently of retrieval; never print the key."""
    import httpx
    from app.llm.registry import registry
    cfg = settings()
    chosen = model or cfg.openrouter_model
    if not cfg.openrouter_api_key.strip():
        return {"ok": False, "reason": "llm_unconfigured", "model_requested": chosen}
    try:
        await registry.validate(chosen)
    except ValueError:
        return {"ok": False, "reason": "model_not_available", "model_requested": chosen}
    try:
        async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds, trust_env=False) as client:
            response = await client.post(cfg.openrouter_base_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': f'Bearer {cfg.openrouter_api_key.strip()}', 'X-Title': 'Estate Intelligence AI'},
                json={'model': chosen, 'messages': [{'role': 'user', 'content': 'Reply with the word OK.'}],
                      'max_tokens': 128, 'stream': False})
        code = response.status_code
        if code != 200:
            reason = {401: 'llm_auth_error', 403: 'llm_auth_error', 429: 'rate_limited',
                      402: 'budget_or_account_error'}.get(code, 'provider_unavailable' if code >= 500 else 'provider_rejected')
            return {'ok': False, 'reason': reason, 'http_status': code, 'model_requested': chosen}
        body = response.json()
        choice = (body.get('choices') or [{}])[0]
        answer = (choice.get('message') or {}).get('content')
        valid = not body.get('error') and choice.get('finish_reason') != 'error' and isinstance(answer, str) and bool(answer.strip())
        return {'ok': valid, 'reason': 'ok' if valid else 'empty_or_invalid_response',
                'http_status': code, 'model_requested': chosen, 'model_used': body.get('model')}
    except httpx.TimeoutException:
        return {'ok': False, 'reason': 'provider_timeout', 'model_requested': chosen}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {'ok': False, 'reason': 'provider_unavailable_or_invalid_response', 'model_requested': chosen}
