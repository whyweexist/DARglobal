"""Real HTTP smoke test, no simulated chatbot answers."""
import json
import os
import urllib.request
from urllib.error import HTTPError, URLError

base = os.environ.get('SMOKE_BASE_URL', 'http://localhost:3000').rstrip('/')
for path in ('/', '/api/v1/health/live', '/api/v1/health/ready', '/api/v1/sources'):
    try:
        with urllib.request.urlopen(base + path, timeout=12) as res:
            payload = res.read(2000)
            print(json.dumps({'path': path, 'status': res.status, 'bytes': len(payload)}))
            if res.status != 200:
                raise SystemExit(2)
    except (HTTPError, URLError) as exc:
        raise SystemExit(f'Smoke failed: {path}: {exc}') from exc
