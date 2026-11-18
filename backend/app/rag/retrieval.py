"""Source-aware FTS5 + sqlite-vec + structured lexical signals, fused using RRF."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine, vector_loaded

log = logging.getLogger(__name__)
STOPWORDS = {"darglobal", "wasalt", "real", "estate", "development", "developments", "documented", "verified", "source", "sources", "current", "give", "list", "all", "these", "those", "their", "them", "its", "then", "also", "instead", "most", "about", "the", "a", "an", "in", "on", "for", "of", "and", "or", "to", "are", "is", "what", "which", "show", "me", "tell", "about", "has", "have", "does", "with", "please", "where", "can", "find", "property", "properties", "project", "projects", "latest", "information", "available", "details"}


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
    return list(dict.fromkeys(x for x in words if (len(x) > 2 or x.isdigit()) and x not in STOPWORDS))[:16]


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
    with engine().connect() as conn:
        if not conn.execute(text("SELECT rowid FROM chunk_vectors LIMIT 1")).first():
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


def property_constraints(query: str) -> tuple[list[str],dict]:
    """Explicit marketplace constraints, never an inferred price conversion."""
    from app.rag.property_query import parse_market_query
    f=parse_market_query(query); clauses=[]; params={}
    if f['cities']:
        cities={x.lower() for x in f['cities']}
        if 'al khobar' in cities: cities.add('khobar')
        clauses.append('lower(p.city) IN :cities'); params['cities']=list(cities)
    if f['categories']:
        clauses.append('('+' OR '.join(f'lower(p.property_type) LIKE :kind{i}' for i in range(len(f['categories'])))+')')
        params.update({f'kind{i}':f'%{kind}%' for i,kind in enumerate(f['categories'])})
        if 'villa' in f['categories']:
            clauses[-1]=clauses[-1][:-1]+" OR lower(p.property_type)='house')"
    if f['transaction']:
        clauses.append('p.transaction_type = :transaction');params['transaction']=f['transaction']
    if f['bedrooms'] is not None:
        clauses.append('p.bedrooms = :beds');params['beds']=f['bedrooms']
    for key,op in [('maximum','<'),('minimum','>')]:
        if key in f:
            clauses.append(f'p.price {op} :{key}');params[key]=f[key]
    if ('maximum' in f or 'minimum' in f) and f['currency']:
        clauses.append('p.currency = :currency');params['currency']=f['currency']
    return clauses,params


def constrained_urls(query: str, sources: list[str]) -> set[str] | None:
    # Strict constraints apply to marketplace listing retrieval, not developer
    # research questions. Enforce them on every Wasalt retrieval branch.
    clauses,params=property_constraints(query)
    if not clauses or 'wasalt' not in sources: return None
    # City-only general research may cite a project or category page.
    if set(params)=={'cities'}: return None
    sql=text("SELECT p.url FROM properties p WHERE p.source_id = 'wasalt' AND "+' AND '.join(clauses))
    if 'cities' in params: sql=sql.bindparams(__import__('sqlalchemy').bindparam('cities',expanding=True))
    with engine().connect() as conn:
        return set(conn.execute(sql,params).scalars())


def structured_search(query: str, source_filter: list[str] | None = None, limit: int = 20) -> list[Evidence]:
    tokens=significant_tokens(query)
    if not tokens: return []
    sources=source_filter or ['darglobal','wasalt']
    clauses,params=property_constraints(query)
    params['sources']=sources;params['limit']=max(limit*12,240)
    stmt=text('SELECT p.source_id,p.url,p.title,p.city,p.country,p.property_type FROM properties p WHERE p.source_id IN :sources '+(' AND '+' AND '.join(clauses) if clauses else '')+' ORDER BY p.observed_at DESC LIMIT :limit').bindparams(__import__('sqlalchemy').bindparam('sources',expanding=True))
    if 'cities' in params: stmt=stmt.bindparams(__import__('sqlalchemy').bindparam('cities',expanding=True))
    with engine().connect() as conn:
        ranked=[]
        for row in conn.execute(stmt,params):
            names=' '.join(str(v or '') for v in (row.title,row.city,row.country,row.property_type)).casefold()
            overlap=sum(t.rstrip('s') in names for t in tokens)
            if overlap or clauses: ranked.append((overlap,row))
        ranked.sort(key=lambda x:x[0],reverse=True)
        results=[]
        for score,row in ranked[:limit]:
            chunk=conn.execute(text('SELECT c.id,c.text,c.heading,d.fetched_at FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.url=:url ORDER BY c.ordinal LIMIT 1'),{'url':row.url}).first()
            if chunk: results.append(Evidence(chunk.id,row.title,row.source_id,row.url,chunk.text,str(chunk.fetched_at),score,chunk.heading))
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
        # Require substantive word-level support and prefer specific pages over a
        # homepage that merely mentions the requested source or a generic keyword.
        allowed = constrained_urls(query, sources or ['darglobal','wasalt'])
        structured_ids = {e.chunk_id for branch,weight in results if weight==0.8 for e in branch}
        filtered = [ev for ev in ordered if (self._plausible(query, ev) or (allowed is not None and ev.source == 'wasalt' and ev.url in allowed and ev.chunk_id in structured_ids))
                    and (allowed is None or ev.source != 'wasalt' or ev.url in allowed)]
        terms = set(significant_tokens(query))
        def quality(ev):
            words = set(re.findall(r"\w+", (ev.text + " " + ev.title).casefold()))
            title_words = set(significant_tokens(ev.title))
            return (len(terms & words) / max(1, len(terms)),
                    len(terms & title_words), scores[ev.chunk_id])
        filtered.sort(key=quality, reverse=True)
        distinct = []
        url_counts = {}
        for ev in filtered:
            words = set(re.findall(r"\w+", ev.text.casefold()))
            duplicate = any(len(words & old) / max(1, min(len(words), len(old))) >= .80
                            and not (ev.source == prior.source == "wasalt" and ev.url != prior.url)
                            for prior, old in distinct)
            if duplicate or url_counts.get(ev.url, 0) >= 3:
                continue
            distinct.append((ev, words))
            url_counts[ev.url] = url_counts.get(ev.url, 0) + 1
        return self.reranker.rerank(query, [ev for ev,_ in distinct], top_k), degraded

    @staticmethod
    def _plausible(query: str, ev: Evidence) -> bool:
        terms = set(significant_tokens(query))
        if not terms:
            return False
        words = set(significant_tokens(ev.title)) | set(re.findall(r"\w+", ev.text.casefold()))
        # Accept singular/plural morphological variants, but not arbitrary substrings.
        stem = lambda w: w[:-1] if len(w) > 4 and w.endswith('s') else w
        terms = {stem(t) for t in terms}
        words = {stem(t) for t in words}
        overlap = terms & words
        # More specific questions must match more than one concept. Generic
        # property/developer tokens are not sufficient by themselves.
        minimum = 1 if len(terms) == 1 else max(2, (len(terms)+1)//2)
        return len(overlap) >= minimum
