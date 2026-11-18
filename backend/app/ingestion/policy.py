"""Permission-aware official-source fetch policy. No scraping bypass mechanisms."""
from __future__ import annotations
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from app.core.config import settings

log = logging.getLogger(__name__)
USER_AGENT = "EstateIntelligenceResearchBot/1.0 (+contact: repository administrator)"
ALLOWED = {
    "darglobal": {"darglobal.co.uk", "www.darglobal.co.uk"},
    "wasalt": {"wasalt.sa", "www.wasalt.sa"},
}


class PolicyDenied(ValueError):
    pass


@dataclass(frozen=True)
class Permission:
    allowed: bool
    reason: str


def assert_source_authorized(source: str) -> None:
    s = settings()
    if source not in ALLOWED:
        raise PolicyDenied("Unknown source")
    if source == "darglobal" and not s.darglobal_enabled:
        raise PolicyDenied("DarGlobal ingestion disabled by configuration")
    if source == "wasalt" and not s.wasalt_permitted:
        raise PolicyDenied("Wasalt collection requires independently documented authorization; use authorized import")


def validate_official_url(url: str, source: str) -> str:
    assert_source_authorized(source)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED[source] or parsed.port not in (None, 443):
        raise PolicyDenied("Only HTTPS official-source hosts are allowed")
    if parsed.username or parsed.password or parsed.fragment:
        raise PolicyDenied("URL credentials/fragments are not permitted")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PolicyDenied(f"DNS lookup failed: {type(exc).__name__}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise PolicyDenied("Source resolved to non-public network address")
    return url


class SourcePolicy:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.cache: dict[str, RobotFileParser] = {}

    async def check(self, url: str, source: str) -> None:
        validate_official_url(url, source)
        host = (urlparse(url).hostname or "").lower()
        if host not in self.cache:
            robots_url = f"https://{host}/robots.txt"
            response = await self.client.get(robots_url, follow_redirects=False, timeout=10)
            if response.status_code in (301, 302, 307, 308):
                target = urljoin(robots_url, response.headers.get("location", ""))
                validate_official_url(target, source)
                if not target.endswith("/robots.txt"):
                    raise PolicyDenied("robots.txt redirected to a non-robots document")
                response = await self.client.get(target, follow_redirects=False, timeout=10)
            if response.status_code != 200:
                raise PolicyDenied(f"robots.txt unavailable (HTTP {response.status_code}); fail closed")
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            self.cache[host] = parser
        if not self.cache[host].can_fetch(USER_AGENT, url):
            raise PolicyDenied("robots.txt disallows this URL")


async def permitted_request(client: httpx.AsyncClient, policy: SourcePolicy, url: str, source: str,
                            size_limit: int = 1_500_000) -> tuple[str, str]:
    # Every same-source redirect must pass the same URL/robots checks; no cross-origin bypass.
    current = url
    for _ in range(4):
        await policy.check(current, source)
        async with client.stream("GET", current, follow_redirects=False, timeout=15) as response:
            if response.status_code in (301, 302, 307, 308):
                target = urljoin(current, response.headers.get("location", ""))
                validate_official_url(target, source)
                current = target
                continue
            response.raise_for_status()
            if "html" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected HTML response")
            result = bytearray()
            async for chunk in response.aiter_bytes():
                result.extend(chunk)
                if len(result) > size_limit:
                    raise ValueError("Document exceeds allowed response size")
            return current, result.decode(response.encoding or "utf-8", errors="replace")
    raise PolicyDenied("Too many redirects or redirect loop")
