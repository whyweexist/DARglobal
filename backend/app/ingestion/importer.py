"""Import a legitimate, authorized source export. No demo or fabricated records."""
import csv
import json
from pathlib import Path
from urllib.parse import urlparse
from app.core.config import settings
from app.ingestion.parser import ExtractedPage
from app.ingestion.policy import ALLOWED, PolicyDenied, assert_source_authorized
from app.rag.indexer import upsert_page


def import_authorized_file(path: Path, source: str, authorization_reference: str) -> dict:
    if source not in ALLOWED:
        raise ValueError("Unknown source")
    if not authorization_reference.strip():
        raise PolicyDenied("A documented authorization reference is mandatory for imported data")
    if source == "wasalt" and not settings().wasalt_permitted:
        raise PolicyDenied("Set WASALT_AUTHORIZED and WASALT_AUTHORIZATION_REFERENCE before importing")
    assert_source_authorized(source)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            items = list(csv.DictReader(f))
    elif path.suffix.lower() == ".json":
        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError("Expected top-level JSON array")
    else:
        raise ValueError("Only CSV and JSON source exports are supported")
    result = {"inserted": 0, "updated": 0, "skipped": 0, "records": len(items)}
    for obj in items:
        if not isinstance(obj, dict):
            result["skipped"] += 1
            continue
        url = str(obj.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED[source]:
            result["skipped"] += 1
            continue
        title = str(obj.get("title", ""))[:500]
        body = str(obj.get("content") or obj.get("description") or "")
        if not title or len(body.strip()) < 45:
            result["skipped"] += 1
            continue
        record = ExtractedPage(title=title, sections=[(title, body)], language=str(obj.get("language", "en"))[:10])
        outcome = upsert_page(source, url, record, method="authorized_import")
        result[outcome] += 1
    return result
