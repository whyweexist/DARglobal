"""HTML-to-structured-source extraction with low boilerplate retention."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup


@dataclass
class ExtractedPage:
    title: str
    sections: list[tuple[str, str]]
    language: str = "en"
    facts: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join((f"{heading}\n{body}" if heading else body) for heading, body in self.sections)


def parse_html(html: str, source: str) -> ExtractedPage:
    properties = jsonld_properties(html)
    soup = BeautifulSoup(html, "lxml")
    for unwanted in soup.select("script, style, nav, footer, header, aside, form, svg, noscript, iframe, button, [role=navigation]"):
        unwanted.decompose()
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:500]
    lang = (soup.html.get("lang", "en") if soup.html else "en")[:10]
    root = soup.select_one("main, article, [role=main]") or soup.body or soup
    sections: list[tuple[str, str]] = []
    current_heading = title
    current: list[str] = []

    def flush():
        if current:
            value = re.sub(r"\s+", " ", " ".join(current)).strip()
            if len(value) >= 45 and value not in (s[1] for s in sections):
                sections.append((current_heading, value))
            current.clear()

    # Restrict to meaningful text blocks to avoid repeated layout elements.
    for node in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dd"], recursive=True):
        if node.find_parent(["nav", "footer", "aside", "form"]):
            continue
        if node.name in ("h1", "h2", "h3", "h4"):
            flush()
            current_heading = node.get_text(" ", strip=True)[:250] or title
        else:
            if node.find_parent(["li", "p", "td", "dd"]):
                continue
            text = node.get_text(" ", strip=True)
            if 12 <= len(text) <= 2500:
                current.append(text)
    flush()
    facts = {"properties": properties[:15]} if properties else {}
    return ExtractedPage(title=title or "Untitled page", sections=sections, language=lang, facts=facts)


def jsonld_properties(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    records = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.string or node.get_text())
        except (ValueError, TypeError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        for item in stack:
            if not isinstance(item, dict):
                continue
            stack.extend(x for x in item.get("@graph", []) if isinstance(x, dict))
            kind = item.get("@type", [])
            kind = [kind] if isinstance(kind, str) else kind
            if any(x in {"Product", "Residence", "Apartment", "House", "RealEstateListing", "Accommodation"} for x in kind):
                records.append(item)
    return records
