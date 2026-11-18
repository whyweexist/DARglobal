#!/usr/bin/env python3
"""Standalone Wasalt adapter with required authorization gate."""
import argparse
import asyncio
import json
from app.db.schema import initialize
from app.ingestion.wasalt import scrape_wasalt
from app.ingestion.jobs import record_ingestion

async def main():
    p = argparse.ArgumentParser(description="Authorized Wasalt ingestion")
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--engine", choices=("httpx", "scrapling"), default=None,
                   help="Select HTTPX or the optional Scrapling HTTP/CSS engine")
    p.add_argument("--query", default="", help="Focus collection on a city, property type or sale/rent")
    args = p.parse_args()
    initialize()
    result = await scrape_wasalt(max_pages=args.max_pages, dry_run=args.dry_run, engine=args.engine, query=args.query)
    if not args.dry_run:
        record_ingestion(result)
    print(json.dumps(result.__dict__, indent=2))
    if result.status in {"permission_required", "unavailable"}:
        raise SystemExit(2)

if __name__ == "__main__":
    asyncio.run(main())
