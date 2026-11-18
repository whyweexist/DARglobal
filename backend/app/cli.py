"""Operational commands used by Docker, Makefile and Codespaces."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
from pathlib import Path
from importlib.metadata import version
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.schema import initialize, rebuild_fts
from app.ingestion.darglobal import scrape_darglobal
from app.ingestion.wasalt import scrape_wasalt
from app.ingestion.jobs import record_ingestion, refresh_due
from app.ingestion.fetchers import scrapling_available
from app.rag.indexer import index_missing_vectors

log = logging.getLogger(__name__)


async def ingest(force: bool = False, engine: str | None = None) -> list[dict]:
    reports = []
    for name, scrape in [("darglobal", scrape_darglobal), ("wasalt", scrape_wasalt)]:
        if not force and not refresh_due(name):
            reports.append({"source": name, "status": "fresh_skip"})
            continue
        try:
            result = await scrape(engine=engine)
            record_ingestion(result)
            reports.append(result.__dict__)
        except Exception as exc:
            log.exception("Ingestion failed for %s", name)
            reports.append({"source": name, "status": "failed", "reason": type(exc).__name__})
    return reports


def main():
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "ingest", "index", "doctor", "backup", "chat", "models", "stats", "search", "export", "check-ai"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--engine", choices=("httpx", "scrapling"), default=None)
    parser.add_argument("--path", default="/data/backups/estate-backup.db")
    parser.add_argument("--model", default=None)
    parser.add_argument("--question", default=None)
    parser.add_argument("--source", choices=("all","darglobal","wasalt"), default="all")
    parser.add_argument("--no-live-search", action="store_true")
    parser.add_argument("--output", default="../data/exports")
    args = parser.parse_args()
    initialize()
    if args.command == "bootstrap":
        report = asyncio.run(ingest(force=args.force, engine=args.engine)) if settings().scrape_on_boot else []
        indexes = index_missing_vectors()
        print(json.dumps({"ingestion": report, "index": indexes}, default=str))
    elif args.command == "ingest":
        print(json.dumps(asyncio.run(ingest(force=args.force, engine=args.engine)), default=str))
    elif args.command == "index":
        rebuild_fts()
        print(json.dumps(index_missing_vectors()))
    elif args.command == "doctor":
        from app.db.session import vector_loaded, engine
        print(json.dumps({"db": str(engine().url).split("?")[0], "sqlite_vec": vector_loaded(),
                          "openrouter_configured": bool(settings().openrouter_api_key),
                          "wasalt_authorized": settings().wasalt_permitted,
                          "scraper_engine": settings().scraper_engine,
                          "wasalt_engine": settings().effective_wasalt_engine,
                          "apify_configured": bool(settings().apify_enabled and settings().apify_token),
                          "apify_live_search": settings().apify_live_search,
                          "scrapling_installed": scrapling_available(),
                          "scrapling_version": version("scrapling") if scrapling_available() else None}))
    elif args.command == "check-ai":
        from app.local_tools import check_ai
        report = asyncio.run(check_ai(args.model))
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            raise SystemExit(2)
    elif args.command in {"chat","models","stats","search","export"}:
        from app.local_tools import chat_loop, model_catalog, stats, export_data
        if args.command == 'chat':
            asyncio.run(chat_loop(args.model or settings().openrouter_model,args.source,args.question,not args.no_live_search))
        elif args.command == 'models':
            print(json.dumps(asyncio.run(model_catalog()),indent=2,ensure_ascii=False))
        elif args.command == 'stats':
            print(json.dumps(stats(),indent=2))
        elif args.command == 'export':
            print(json.dumps(export_data(args.output),indent=2))
        elif args.command == 'search':
            from app.rag.retrieval import HybridRetriever
            if not args.question: parser.error('search requires --question')
            hits, degraded = HybridRetriever().retrieve(args.question,None if args.source=='all' else [args.source])
            print(json.dumps({'results':[hit.to_public(f'E{i}') for i,hit in enumerate(hits,1)],'degraded':degraded},indent=2,ensure_ascii=False))
    elif args.command == "backup":
        import sqlite3
        from app.db.session import engine
        path = Path(args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = engine().raw_connection()
        try:
            with sqlite3.connect(str(path)) as dst:
                src.driver_connection.backup(dst)
        finally:
            src.close()
        print(json.dumps({"backup": str(path)}))

if __name__ == "__main__":
    main()
