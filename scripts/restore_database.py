"""Restore a verified backup into SQLite. Stop API and worker before running."""
import argparse
import sqlite3
from pathlib import Path
from sqlalchemy.engine.url import make_url
from app.core.config import settings

p = argparse.ArgumentParser()
p.add_argument('backup', type=Path)
p.add_argument('--confirm-writers-stopped', action='store_true')
a = p.parse_args()
if not a.confirm_writers_stopped:
    raise SystemExit('Stop API and worker, then add --confirm-writers-stopped')
with sqlite3.connect(str(a.backup)) as db:
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Invalid backup integrity')
target = Path(make_url(settings().database_url).database)
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(str(a.backup)) as src, sqlite3.connect(str(target)) as dest:
    src.backup(dest)
print(f'Restored verified backup into {target}')
