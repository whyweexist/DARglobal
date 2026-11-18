#!/usr/bin/env python3
"""Standalone DarGlobal ingestion script. Run from repository root or backend PYTHONPATH."""
import argparse
import asyncio
import json
from app.db.schema import initialize
from app.ingestion.darglobal import scrape_darglobal
from app.ingestion.jobs import record_ingestion

async def main():
    p = argparse.ArgumentParser(description="Permission-aware DarGlobal ingestion")
    p.add_argument("--max-pages", type=int, default=15)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--engine", choices=("httpx", "scrapling"), default=None,
                   help="Select HTTPX or the optional Scrapling HTTP/CSS engine")
    args = p.parse_args()
    initialize()
    result = await scrape_darglobal(max_pages=args.max_pages, dry_run=args.dry_run, engine=args.engine)
    record_ingestion(result)
    print(json.dumps(result.__dict__, indent=2))
    if result.status in {"permission_required", "unavailable"}:
        raise SystemExit(2)

if __name__ == "__main__":
    asyncio.run(main())
