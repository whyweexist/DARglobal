# Operations and recovery

## Service inspection

```bash
make status
make logs
make doctor
curl -fsS http://localhost:3000/api/v1/health/ready
```

The `/api/v1/sources` endpoint reports actual source status and collected document counts. A value of zero is valid when no authorized ingestion has succeeded.

## Refresh and indexing

- `make refresh`: force permission-aware ingestion.
- `make index`: FTS rebuild and bounded vector backfill (the indexer currently processes up to 150 unembedded chunks per run; run again or configure a larger batch to complete a large backlog).
- `make scrape-darglobal` / `make scrape-wasalt`: independent commands, status code 2 for missing permission.

The worker checks source freshness hourly and stores ingestion run summaries in SQLite. Large datasets need additional explicit queue/migration planning; do not scale multiple writers across hosts.

## Safe backup

`make backup` runs the SQLite Online Backup API inside the container and writes `/data/backups/estate-backup.db` to the persistent volume. Copy verified backup files off-host and encrypt them before storing them in a third-party location. Schedule periodic backups via host cron/systemd. Retain multiple generations.

To check integrity:

```bash
sqlite3 /path/to/backup.db 'PRAGMA integrity_check;'
```

## Restore

1. Stop API and worker, and take an additional backup of the current database.
2. Place the trusted backup file in the container's persistent `/data` volume.
3. Run `PYTHONPATH=/app/backend python /app/scripts/restore_database.py /data/backups/estate-backup.db --confirm-writers-stopped` in a one-off container with volume access, while no writer processes are running.
4. Re-run migrations only if necessary for the restored image revision; verify integrity and FTS count.
5. Restart API/worker and run smoke tests.

Avoid copying `.db` alone while WAL writers remain active. Never run the restoration script against an active production database.

## Common incidents

| Incident | Response |
|---|---|
| OpenRouter 401 | Rotate/verify API key; do not retry blindly |
| OpenRouter 429 | Respect quota window; evidence-only mode remains available |
| Source blocked by robots or terms | Stop collection and seek permission, do not bypass |
| Embedding model unavailable | FTS-only degraded mode; check HF cache and outbound access |
| SQLite locked | Inspect duplicate workers, reduce write concurrency and transaction length |
| Unauthorized source content discovered | Remove content and embeddings, update the source permission state |
| Citation validation failures | Inspect provider logs; no fabricated citation URLs are returned |
| High latency | Profile embedding cold starts, model free-tier response latency, retrieval and I/O |
