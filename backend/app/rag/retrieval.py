"""Source-aware FTS5 + sqlite-vec + structured lexical signals, fused using RRF."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine, vector_loaded

log = logging.getLogger(__name__)
STOPWORDS = {"the", "a", "an", "in", "on", "for", "of", "and", "or", "to", "are", "is", "what", "which", "show", "me", "tell", "about", "has", "have", "does", "with", "please", "where", "can", "find", "price", "property", "properties", "project", "projects", "latest", "information", "available", "details"}


@dataclass
class Evidence:
    chunk_id: int
    title: str
    source: str
    url: str
    text: str
    fetched_at: str
    score: float
    heading: str = ""

    def to_public(self, evidence_id: str) -> dict:
        return {"id": evidence_id, "title": self.title, "source": self.source,
                "url": self.url, "fetched_at": self.fetched_at, "excerpt": self.text[:430]}


def significant_tokens(query: str) -> list[str]:
    words = re.findall(r"[\w\u0600-\u06ff]+", query.casefold(), re.UNICODE)
    return list(dict.fromkeys(x for x in words if len(x) > 2 and x not in STOPWORDS))[:16]


def match_expr(query: str) -> str:
    tokens = significant_tokens(query)
    # FTS operators are never admitted from user input; quote each word.
    return " OR ".join('"' + x.replace('"', '') + '"' for x in tokens)


def _evidence_rows(rows: list, rank: float) -> dict[int, Evidence]:
    return {r.id: Evidence(chunk_id=r.id, title=r.title, source=r.source_id,
                           url=r.url, text=r.text, fetched_at=str(r.fetched_at),
                           heading=r.heading, score=rank) for r in rows}


def lexical_search(query: str, source_filter: list[str] | None = None, limit: int = 20) -> list[Evidence]:
    expression = match_expr(query)
    if not expression:
        return []
    sources = source_filter or ["darglobal", "wasalt"]
    with engine().connect() as conn:
        rows = conn.execute(text("""SELECT c.id, c.text, c.heading, d.title, d.url, d.source_id, d.fetched_at,
            bm25(chunks_fts, 1.0, 2.0) AS relevance
            FROM chunks_fts JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH :q AND d.source_id IN :sources
            ORDER BY relevance ASC LIMIT :limit""").bindparams(__import__('sqlalchemy').bindparam("sources", expanding=True)),
            {"q": expression, "sources": sources, "limit": limit}).all()
    return [Evidence(chunk_id=r.id, title=r.title, source=r.source_id,
                     url=r.url, text=r.text, fetched_at=str(r.fetched_at), score=-float(r.relevance),
                     heading=r.heading) for r in rows]


def semantic_search(query: str, source_filter: list[str] | None = None, limit: int = 20) -> list[Evidence]:
    if not vector_loaded():
        return []
    from app.rag.embeddings import encode, serialize
    values = encode([query])
    if not values:
        return []
    sources = source_filter or ["darglobal", "wasalt"]
    # vec0 expects an explicit k and accepts the binary float32 query embedding.
    with engine().connect() as conn:
        nearest = conn.execute(text("""SELECT rowid, distance FROM chunk_vectors
            WHERE embedding MATCH :v AND k = :k ORDER BY distance"""),
            {"v": serialize(values[0]), "k": limit * 3}).all()
        if not nearest:
            return []
        ids = [r.rowid for r in nearest]
        rows = conn.execute(text("""SELECT c.id, c.text, c.heading, d.title, d.url, d.source_id, d.fetched_at
            FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id IN :ids AND d.source_id IN :sources""").bindparams(
            __import__('sqlalchemy').bindparam('ids', expanding=True),
            __import__('sqlalchemy').bindparam('sources', expanding=True)),
            {"ids": ids, "sources": sources}).all()
    byid = _evidence_rows(rows, 0.0)
    return [Evidence(**{**byid[r.rowid].__dict__, "score": -float(r.distance)})
            for r in nearest if r.rowid in byid][:limit]


def structured_search(query: str, source_filter: list[str] | None = None, limit: int = 20) -> list[Evidence]:
    """Prioritize source-verified property metadata; enforce explicit numerical constraints."""
    tokens = significant_tokens(query)
    if not tokens:
        return []
    sources = source_filter or ["darglobal", "wasalt"]
    lower = query.casefold()
    import re
    bound = re.search(r"(?:under|below|less than|over|above|more than)\s*(?:[$£€]|sar|aed)?\s*([\d,]+)", lower)
    bed = re.search(r"(\d+)\s*(?:bed|bedroom)", lower)
    with engine().connect() as conn:
        properties = conn.execute(text("""SELECT p.source_id, p.url, p.title, p.city, p.country,
              p.property_type, p.price, p.currency, p.bedrooms, p.bathrooms
              FROM properties p WHERE p.source_id IN :sources LIMIT 300""").bindparams(
              __import__('sqlalchemy').bindparam('sources', expanding=True)), {"sources": sources}).all()
        ranked = []
        for row in properties:
            names = " ".join(str(v or "") for v in (row.title,row.city,row.country,row.property_type)).casefold()
            matches = sum(t in names for t in tokens)
            if not matches:
                continue
            if bed and row.bedrooms != int(bed.group(1)):
                continue
            if bound:
                if row.price is None:
                    continue
                threshold = float(bound.group(1).replace(",", ""))
                if ("under" in lower or "below" in lower or "less than" in lower) and row.price >= threshold:
                    continue
                if ("over" in lower or "above" in lower or "more than" in lower) and row.price <= threshold:
                    continue
            ranked.append((matches, row))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        results = []
        for score, row in ranked[:limit]:
            chunk = conn.execute(text("""SELECT c.id,c.text,c.heading,d.fetched_at
                FROM chunks c JOIN documents d ON c.document_id=d.id
                WHERE d.url=:url LIMIT 1"""), {"url": row.url}).first()
            if chunk:
                results.append(Evidence(chunk_id=chunk.id, title=row.title,source=row.source_id,
                                        url=row.url, text=chunk.text, fetched_at=str(chunk.fetched_at),
                                        score=score, heading=chunk.heading))
    return results


class IdentityReranker:
    def rerank(self, query: str, candidates: list[Evidence], top_k: int) -> list[Evidence]:
        return candidates[:top_k]


class HybridRetriever:
    def __init__(self):
        self.reranker = IdentityReranker()

    def retrieve(self, query: str, sources: list[str] | None = None, top_k: int | None = None) -> tuple[list[Evidence], list[str]]:
        top_k = top_k or settings().retrieval_top_k
        results = []
        degraded = []
        for label, fn, weight in [("lexical", lexical_search, 1.2),
                                   ("semantic", semantic_search, 1.0),
                                   ("structured", structured_search, 0.8)]:
            try:
                results.append((fn(query, sources, limit=20), weight))
            except Exception as exc:
                degraded.append(label)
                log.warning("retriever degraded: branch=%s error=%s", label, type(exc).__name__)
        merged: dict[int, Evidence] = {}
        scores: dict[int, float] = {}
        for branch, weight in results:
            for rank, evidence in enumerate(branch):
                merged[evidence.chunk_id] = evidence
                scores[evidence.chunk_id] = scores.get(evidence.chunk_id, 0) + weight / (60 + rank + 1)
        ordered = sorted(merged.values(), key=lambda ev: scores[ev.chunk_id], reverse=True)
        # Conservative lexical support for named entity relevance; semantic-only matches
        # remain eligible if sufficiently related but require at least one significant term
        # for evidence-gating downstream.
        filtered = [ev for ev in ordered if self._plausible(query, ev)]
        return self.reranker.rerank(query, filtered, top_k), degraded

    @staticmethod
    def _plausible(query: str, ev: Evidence) -> bool:
        tokens = significant_tokens(query)
        if not tokens:
            return False
        searchable = (ev.text + " " + ev.title).casefold()
        overlap = sum(t in searchable for t in tokens)
        return overlap >= 1
