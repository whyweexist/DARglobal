"""DarGlobal source adapter. Robot and domain restrictions enforced centrally."""
from app.ingestion.crawler import crawl, CrawlReport


async def scrape_darglobal(*, max_pages: int | None = None, dry_run: bool = False, engine: str | None = None) -> CrawlReport:
    return await crawl("darglobal", "https://darglobal.co.uk/", max_pages=max_pages, dry_run=dry_run, engine=engine)
