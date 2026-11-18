"""Deterministic evidence-first orchestration, with bounded live discovery."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from app.core.config import settings
from app.rag.retrieval import HybridRetriever
from app.rag.grounding import evidence_only
from app.llm.gateway import grounded_answer
from app.agents.tools import discover_and_ingest
from app.memory.context import plan_query, has_requested_fields

log = logging.getLogger(__name__)

class RAGOrchestrator:
    def __init__(self):
        self.retriever = HybridRetriever()

    async def answer(self, question: str, model: str, sources: list[str], allow_live_search: bool = True,
                     on_status=None, history: list[dict] | None = None) -> dict:
        cfg = settings()
        plan = plan_query(question, history)
        activities = []
        degraded = []
        discovered = False
        hits = []
        async def status(name: str, info: str):
            if on_status:
                await on_status({'phase':name,'detail':info})
        async def retrieve():
            nonlocal hits, degraded
            await status('retrieving','Searching indexed evidence for the current question')
            hits, issues = await asyncio.to_thread(self.retriever.retrieve,plan.search_query,sources)
            degraded = sorted(set(degraded+issues))
        async def live():
            nonlocal activities, discovered
            if discovered or not allow_live_search or not cfg.rag_live_search:
                return False
            discovered = True
            await status('source_search','Checking permitted official sources for missing information')
            try:
                activities = await asyncio.wait_for(discover_and_ingest(plan.search_query,sources),cfg.agent_max_seconds)
            except TimeoutError:
                activities = [{'tool':'discover_official_source_pages','status':'timeout','detail':'Search deadline exceeded'}]
            except Exception as exc:
                log.warning('Live discovery failed: %s',type(exc).__name__)
                activities = [{'tool':'discover_official_source_pages','status':'unavailable','detail':type(exc).__name__}]
            await retrieve()
            return True
        try:
            async with asyncio.timeout(cfg.chat_deadline_seconds):
                await retrieve()
                fresh_requested = any(w in question.casefold() for w in ('latest','current','today','currently','right now','live availability'))
                if not hits or not has_requested_fields(plan.fields,hits) or fresh_requested:
                    await live()
                if not hits:
                    result = evidence_only([], 'no_evidence')
                elif not has_requested_fields(plan.fields,hits):
                    result = evidence_only([], 'insufficient_evidence')
                else:
                    await status('generating','Generating and validating a new answer with OpenRouter')
                    # Keep current wording as the question; the contextual query is
                    # only for retrieval. Prior assistant text is marked untrusted.
                    result = await grounded_answer(plan.question,hits,model,plan.history)
                    if result['status']=='insufficient_evidence' and await live():
                        if hits and has_requested_fields(plan.fields,hits):
                            result = await grounded_answer(plan.question,hits,model,plan.history)
        except TimeoutError:
            result = evidence_only(hits,'request_deadline')
        if result['status'] in {'no_evidence','insufficient_evidence'} and activities:
            statuses = {a.status if hasattr(a,'status') else a.get('status') for a in activities}
            if not statuses.intersection({'completed'}):
                result['answer'] += ' Official-source lookup returned no usable additional evidence or was unavailable; see search activity.'
        result.update({'model_requested':model,'retrieval_mode':'hybrid_plus_live' if discovered else 'hybrid',
                       'retrieval_query':plan.search_query,'retrieval_degraded':degraded,
                       'tool_activity':[a.public() if hasattr(a,'public') else a for a in activities],
                       'observed_at':datetime.now(timezone.utc).isoformat()})
        return result
