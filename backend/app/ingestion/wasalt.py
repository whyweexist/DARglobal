"""Wasalt adapter. Collection is never attempted absent documented authorization."""
from app.ingestion.crawler import crawl, CrawlReport


async def scrape_wasalt(*, max_pages: int | None = None, dry_run: bool = False, engine: str | None = None) -> CrawlReport:
    return await crawl("wasalt", "https://wasalt.sa/en", max_pages=max_pages, dry_run=dry_run, engine=engine)
