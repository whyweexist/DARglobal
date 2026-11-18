"""Exercise the real pinned package on a loopback fixture, not a source website.

The low-level transport is tested in isolation; production always calls it
through fetch_allowed_page with source and robots validation.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import pytest

from app.ingestion.fetchers import ScraplingCrawlSession
from app.ingestion.policy import USER_AGENT


@pytest.mark.asyncio
async def test_real_scrapling_session_contract():
    pytest.importorskip('scrapling.fetchers')
    assert version('scrapling') == '0.5.1'
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.path, self.headers.get('User-Agent')))
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/listing')
                self.end_headers()
                return
            body = '<html><title>Local test</title><a href="/listing">Listing</a></html>'.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f'http://127.0.0.1:{server.server_port}'
    try:
        async with ScraplingCrawlSession() as session:
            first = await session.get(root + '/listing')
            second = await session.get(root + '/redirect')
            assert first.status == 200 and isinstance(first.body, bytes)
            assert first.css('a::attr(href)').getall() == ['/listing']
            assert second.status == 302
        assert session._session is None
        assert observed == [('/listing', USER_AGENT), ('/redirect', USER_AGENT)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
