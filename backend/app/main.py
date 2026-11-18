"""Estate Intelligence FastAPI application."""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.models import Conversation, Message, Document, IngestionRun, Source
from app.db.schema import initialize
from app.db.session import engine, session_factory, vector_loaded
from app.api.schemas import ChatRequest
from app.api.security import check_rate
from app.agents.orchestrator import RAGOrchestrator
from app.llm.registry import registry
from app.rag.retrieval import HybridRetriever

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield


app = FastAPI(title="Estate Intelligence API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings().cors_origins, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "X-Conversation-Token"], allow_credentials=False)


@app.middleware("http")
async def defensive_headers(request: Request, call_next):
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 18_000:
        raise HTTPException(413, "Request body too large")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:90]
    return response


def get_conversation(body: ChatRequest) -> tuple[str, str, list[dict]]:
    """Persist minimal messages under a high-entropy per-conversation bearer token."""
    token = body.conversation_token
    with session_factory()() as db:
        if body.conversation_id:
            convo = db.get(Conversation, body.conversation_id)
            if not convo or not token or not secrets.compare_digest(convo.token_hash, hashlib.sha256(token.encode()).hexdigest()):
                raise HTTPException(403, "Conversation credentials invalid")
            recent = db.scalars(select(Message).where(Message.conversation_id == convo.id)
                                .order_by(Message.id.desc()).limit(12)).all()
            history = [{"role": m.role, "content": m.text} for m in reversed(recent)]
            return convo.id, token, history
        new_id, new_token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        db.add(Conversation(id=new_id, token_hash=hashlib.sha256(new_token.encode()).hexdigest()))
        db.commit()
        return new_id, new_token, []


def save_exchange(conversation_id: str, user: str, assistant: str):
    with session_factory()() as db:
        db.add_all([Message(conversation_id=conversation_id, role="user", text=user),
                    Message(conversation_id=conversation_id, role="assistant", text=assistant)])
        db.commit()


async def run_chat(body: ChatRequest, request: Request, on_status=None) -> dict:
    check_rate(request)
    try:
        await registry.validate(body.model)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    cid, ctoken, history = get_conversation(body)
    try:
        result = await RAGOrchestrator().answer(body.message, body.model,
                                                 sorted(set(body.source_filter)), body.allow_live_search, on_status, history)
    except Exception as exc:
        log.exception("Chat orchestration failed")
        raise HTTPException(503, "Research service unavailable; retry later") from exc
    save_exchange(cid, body.message, result["answer"])
    return {**result, "conversation_id": cid, "conversation_token": ctoken,
            "request_id": str(uuid.uuid4())}


@app.post("/api/v1/chat")
async def chat(body: ChatRequest, request: Request):
    return await run_chat(body, request)


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/v1/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    async def events():
        q: asyncio.Queue = asyncio.Queue()

        async def notify(payload):
            await q.put(payload)

        async def perform():
            try:
                return await run_chat(body, request, notify)
            finally:
                await q.put(None)

        task = asyncio.create_task(perform())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), 10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                yield sse("activity", item)
            result = await task
            # Stream only after grounding verification to prevent unverified claims from rendering.
            # This provides progressive text delivery without leaking unverified model tokens.
            answer = result.pop("answer", "")
            for i in range(0, len(answer), 110):
                yield sse("delta", {"text": answer[i:i + 110]})
            yield sse("done", result)
        except HTTPException as exc:
            yield sse("error", {"message": exc.detail, "status": exc.status_code})
        except Exception:
            log.exception("SSE failed")
            yield sse("error", {"message": "Chat service unavailable", "status": 503})
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/v1/models")
async def models(refresh: bool = False):
    return await registry.options(refresh=refresh)


@app.get("/api/v1/sources")
@app.get("/api/v1/sources/status")
async def sources():
    with session_factory()() as db:
        sources = db.scalars(select(Source)).all()
        result = []
        for src in sources:
            count = db.scalar(select(func.count(Document.id)).where(Document.source_id == src.id))
            latest = db.scalars(select(IngestionRun).where(IngestionRun.source_id == src.id)
                                .order_by(IngestionRun.id.desc()).limit(1)).first()
            result.append({"id": src.id, "name": src.name, "url": src.base_url,
                           "documents": count, "engine": settings().effective_wasalt_engine if src.id == "wasalt" else settings().scraper_engine, "permitted": (settings().wasalt_permitted if src.id == "wasalt" else settings().darglobal_enabled),
                           "permission_note": src.permission_note or ("Authorization required" if src.id == "wasalt" else "Not yet evaluated"),
                           "last_success": str(src.last_success) if src.last_success else None,
                           "last_run_status": latest.status if latest else "not_run"})
        return {"sources": result, "vector_enabled": vector_loaded()}


@app.get("/api/v1/search")
async def search(request: Request, q: str = Query(min_length=3, max_length=250), source: str = "all"):
    check_rate(request)
    if source not in {"all", "darglobal", "wasalt"}:
        raise HTTPException(422, "Invalid source")
    results, degraded = await asyncio.to_thread(HybridRetriever().retrieve, q,
                                               [source] if source != "all" else None, 8)
    return {"results": [x.to_public(f"E{i}") for i, x in enumerate(results, 1)], "degraded": degraded}


@app.get("/api/v1/health/live")
async def live():
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
async def ready():
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT count(*) FROM chunks_fts")).scalar()
            documents = conn.execute(text("SELECT count(*) FROM documents")).scalar()
            chunks = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        return {"status": "ready", "documents": documents, "chunks": chunks,
                "vector_enabled": vector_loaded(), "ai_configured": bool(settings().openrouter_api_key)}
    except Exception:
        raise HTTPException(503, "Database or search index not ready")


@app.get("/api/v1/conversations/{conversation_id}")
async def conversation(conversation_id: str, x_conversation_token: str = Header(default="")):
    with session_factory()() as db:
        obj = db.get(Conversation, conversation_id)
        if not obj or not secrets.compare_digest(obj.token_hash, hashlib.sha256(x_conversation_token.encode()).hexdigest()):
            raise HTTPException(403, "Conversation credentials invalid")
        msgs = db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                          .order_by(Message.id.asc()).limit(80)).all()
        return {"id": conversation_id, "messages": [{"role": m.role, "text": m.text} for m in msgs]}


@app.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, x_conversation_token: str = Header(default="")):
    with session_factory()() as db:
        obj = db.get(Conversation, conversation_id)
        if not obj or not secrets.compare_digest(obj.token_hash, hashlib.sha256(x_conversation_token.encode()).hexdigest()):
            raise HTTPException(403, "Conversation credentials invalid")
        db.query(Message).filter(Message.conversation_id == conversation_id).delete()
        db.delete(obj)
        db.commit()
        return {"status": "deleted"}
