"""Deterministic evidence-first query control with bounded authorized live source lookup."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from app.core.config import settings
from app.rag.retrieval import HybridRetriever
from app.rag.grounding import evidence_only
from app.llm.gateway import grounded_answer
from app.agents.tools import discover_and_ingest


class RAGOrchestrator:
    def __init__(self):
        self.retriever = HybridRetriever()

    async def answer(self, question: str, model: str, sources: list[str], allow_live_search: bool = True,
                     on_status=None) -> dict:
        activity = []
        async def status(name: str, info: str = ""):
            if on_status:
                await on_status({"phase": name, "detail": info})
        await status("retrieving", "Searching indexed evidence")
        hits, degraded = await asyncio.to_thread(self.retriever.retrieve, question, sources)
        current = any(term in question.casefold() for term in ("latest", "current", "today", "now", "available", "price", "recent", "new"))
        needs_discovery = not hits or current
        if needs_discovery and allow_live_search and settings().rag_live_search:
            await status("source_search", "Checking official permitted sources")
            try:
                activity = await asyncio.wait_for(discover_and_ingest(question, sources), timeout=settings().agent_max_seconds)
                hits, new_degraded = await asyncio.to_thread(self.retriever.retrieve, question, sources)
                degraded = list(set(degraded + new_degraded))
            except TimeoutError:
                activity = [{"tool": "discover_official_source_pages", "status": "timeout", "detail": "Search deadline exceeded"}]
            except Exception as exc:
                activity = [{"tool": "discover_official_source_pages", "status": "unavailable", "detail": type(exc).__name__}]
        await status("verifying", "Evaluating retrieved evidence")
        if not hits:
            result = evidence_only([], "no_evidence")
        else:
            await status("generating", "Generating evidence-grounded response")
            result = await grounded_answer(question, hits, model)
        result.update({"model_requested": model, "retrieval_mode": "hybrid_plus_live" if activity else "hybrid",
                       "retrieval_degraded": degraded,
                       "tool_activity": [a.public() if hasattr(a, "public") else a for a in activity],
                       "observed_at": datetime.now(timezone.utc).isoformat()})
        return result
