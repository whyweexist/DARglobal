"""Scheduled single-writer ingestion worker (separate process)."""
import asyncio
import logging
from app.core.logging import configure_logging
from app.db.schema import initialize
from app.cli import ingest
from app.rag.indexer import index_missing_vectors

async def main():
    configure_logging()
    initialize()
    log = logging.getLogger(__name__)
    while True:
        try:
            result = await ingest()
            indexing = index_missing_vectors()
            log.info("Periodic refresh: %s | indexing: %s", result, indexing)
        except Exception:
            log.exception("Periodic refresh failed")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
