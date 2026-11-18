"""Operational commands used by Docker, Makefile and Codespaces."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
from pathlib import Path
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.schema import initialize, rebuild_fts
from app.ingestion.darglobal import scrape_darglobal
from app.ingestion.wasalt import scrape_wasalt
from app.ingestion.jobs import record_ingestion, refresh_due
from app.rag.indexer import index_missing_vectors

log = logging.getLogger(__name__)


async def ingest(force: bool = False) -> list[dict]:
    reports = []
    for name, scrape in [("darglobal", scrape_darglobal), ("wasalt", scrape_wasalt)]:
        if not force and not refresh_due(name):
            reports.append({"source": name, "status": "fresh_skip"})
            continue
        try:
            result = await scrape()
            record_ingestion(result)
            reports.append(result.__dict__)
        except Exception as exc:
            log.exception("Ingestion failed for %s", name)
            reports.append({"source": name, "status": "failed", "reason": type(exc).__name__})
    return reports


def main():
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "ingest", "index", "doctor", "backup"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--path", default="/data/backups/estate-backup.db")
    args = parser.parse_args()
    initialize()
    if args.command == "bootstrap":
        report = asyncio.run(ingest(force=args.force)) if settings().scrape_on_boot else []
        indexes = index_missing_vectors()
        print(json.dumps({"ingestion": report, "index": indexes}, default=str))
    elif args.command == "ingest":
        print(json.dumps(asyncio.run(ingest(force=args.force)), default=str))
    elif args.command == "index":
        rebuild_fts()
        print(json.dumps(index_missing_vectors()))
    elif args.command == "doctor":
        from app.db.session import vector_loaded, engine
        print(json.dumps({"db": str(engine().url).split("?")[0], "sqlite_vec": vector_loaded(),
                          "openrouter_configured": bool(settings().openrouter_api_key),
                          "wasalt_authorized": settings().wasalt_permitted}))
    elif args.command == "backup":
        import sqlite3
        from app.db.session import engine
        path = Path(args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with engine().raw_connection() as src:
            with sqlite3.connect(str(path)) as dst:
                src.backup(dst)
        print(json.dumps({"backup": str(path)}))

if __name__ == "__main__":
    main()
