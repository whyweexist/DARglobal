"""Durable ingestion audit records and refresh gating."""
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import IngestionRun, Source
from app.db.session import session_factory
from app.ingestion.crawler import CrawlReport


def refresh_due(source: str) -> bool:
    with session_factory()() as db:
        source_row = db.get(Source, source)
        if not source_row or not source_row.last_success:
            return True
        stamp = source_row.last_success.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - stamp >= timedelta(hours=settings().scrape_refresh_hours)


def record_ingestion(report: CrawlReport) -> None:
    with session_factory()() as db:
        row = IngestionRun(source_id=report.source, status=report.status, fetched=report.fetched,
                           inserted=report.inserted, updated=report.updated, skipped=report.skipped,
                           errors=report.errors, detail=f"engine={report.engine}; {report.detail}", finished_at=datetime.now(timezone.utc))
        db.add(row)
        source = db.get(Source, report.source)
        if source:
            source.permitted = report.status != "permission_required"
            source.permission_note = report.detail or ("Permission gate passed; robots respected" if source.permitted else "")
            source.last_checked = datetime.now(timezone.utc)
            if report.fetched and report.status in {"complete", "partial"}:
                source.last_success = datetime.now(timezone.utc)
        db.commit()
