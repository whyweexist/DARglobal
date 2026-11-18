"""Transactional document upserts and incremental vector materialization."""
import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy import delete, text, select
from app.core.config import settings
from app.db.models import Chunk, Document
from app.db.session import session_factory, vector_loaded
from app.ingestion.parser import ExtractedPage
from app.rag.chunker import StructureAwareChunker

log = logging.getLogger(__name__)


def upsert_page(source: str, url: str, page: ExtractedPage, method: str = "authorized_crawl") -> str:
    if not page.sections:
        return "skipped"
    content = page.text
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    cfg = settings()
    builder = StructureAwareChunker(target=cfg.chunk_target_tokens, maximum=cfg.chunk_max_tokens, overlap=cfg.chunk_overlap_tokens)
    chunks = builder.chunk(page.sections)
    if not chunks:
        return "skipped"
    old_chunk_ids: list[int] = []
    with session_factory()() as db:
        doc = db.scalars(select(Document).where(Document.url == url)).first()
        if doc and doc.content_hash == digest:
            doc.fetched_at = datetime.now(timezone.utc)
            db.commit()
            return "skipped"
        outcome = "updated" if doc else "inserted"
        if not doc:
            doc = Document(source_id=source, url=url, title=page.title, content=content,
                           content_hash=digest, language=page.language, method=method)
            db.add(doc)
            db.flush()
        else:
            old_chunk_ids = [x.id for x in doc.sections]
            if vector_loaded():
                for chunk_id in old_chunk_ids:
                    db.execute(text("DELETE FROM chunk_vectors WHERE rowid=:id"), {"id": chunk_id})
            db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            db.flush()
            doc.title, doc.content, doc.content_hash = page.title, content, digest
            doc.language, doc.method = page.language, method
            doc.fetched_at = datetime.now(timezone.utc)
        for idx, c in enumerate(chunks):
            db.add(Chunk(document_id=doc.id, ordinal=idx, heading=c.heading,
                         text=c.text, tokens=c.tokens, checksum=c.checksum))
        db.commit()
    if page.facts.get("properties"):
        from app.ingestion.properties import save_structured
        save_structured(source, url, page.facts["properties"])
    return outcome


def index_missing_vectors(limit: int = 150) -> dict:
    from app.db.session import engine
    if not vector_loaded():
        return {"indexed": 0, "status": "degraded", "reason": "sqlite-vec unavailable"}
    with session_factory()() as db:
        pending = db.scalars(select(Chunk).where(Chunk.embedding_model.is_(None)).limit(limit)).all()
        if not pending:
            return {"indexed": 0, "status": "ready"}
        ids = [c.id for c in pending]
        texts = [c.text for c in pending]
        checksums = [c.checksum for c in pending]
    try:
        from app.rag.embeddings import encode, serialize
        vectors = encode(texts)
    except Exception as exc:
        log.warning("Semantic indexing deferred: %s", type(exc).__name__)
        return {"indexed": 0, "status": "degraded", "reason": type(exc).__name__}
    indexed = 0
    with engine().begin() as conn:
        for cid, vec, checksum in zip(ids, vectors, checksums):
            if not conn.execute(text("SELECT id FROM chunks WHERE id=:id AND checksum=:checksum"), {"id": cid, "checksum": checksum}).first():
                continue
            if len(vec) != settings().embedding_dim:
                raise RuntimeError("Embedding dimension mismatch. Recreate vector index with proper migration")
            conn.execute(text("INSERT OR REPLACE INTO chunk_vectors(rowid,embedding) VALUES (:id,:v)"),
                         {"id": cid, "v": serialize(vec)})
            conn.execute(text("UPDATE chunks SET embedding_model=:m WHERE id=:id"),
                         {"id": cid, "m": settings().embedding_model})
            indexed += 1
    return {"indexed": indexed, "status": "ready"}
