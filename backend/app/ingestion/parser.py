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


def parse_html(html: str, source: str, *, url: str = "") -> ExtractedPage:
    if source == "wasalt" and url:
        from app.ingestion.wasalt_parser import parse_wasalt
        return parse_wasalt(html, url)
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
    seen_blocks: set[str] = set()

    def flush():
        if current:
            value = "\n\n".join(current).strip()
            if len(value) >= 12 and value not in (s[1] for s in sections):
                sections.append((current_heading, value))
            current.clear()

    # Restrict to meaningful text blocks to avoid repeated layout elements.
    for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "dt", "dd", "div", "span"], recursive=True):
        if node.find_parent(["nav", "footer", "aside", "form"]):
            continue
        if node.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            flush()
            current_heading = node.get_text(" ", strip=True)[:250] or title
        else:
            if node.find_parent(["li", "p", "td", "dd", "dt"]):
                continue
            # Leaf-only text blocks retain visible specification cards without
            # duplicating nested layout, navigation or entire page containers.
            if node.name in ('div','span') and (node.find(['div','span','p','li','h1','h2','h3','h4','h5','h6','table','dd','dt']) or node.find_parent(['a','button'])):
                continue
            text = node.get_text(" ", strip=True)
            normalized = re.sub(r"\s+", " ", text).strip()
            if (len(normalized) >= 12 or (node.name in ("dt","dd","td","div","span") and len(normalized)>=2)) and len(normalized)<=12000 and normalized.casefold() not in seen_blocks:
                current.append(normalized)
                seen_blocks.add(normalized.casefold())
    flush()
    # Catalogue project cards may be div/span-only anchor content and are
    # otherwise lost by paragraph-based extraction. Read actual visible labels.
    if source == "darglobal" and url:
        from urllib.parse import urlparse
        if urlparse(url).path.startswith('/projects'):
            from app.ingestion.crawler import catalog_links
            labels = list(dict.fromkeys(label for label in catalog_links(html, url, source).values()
                                        if len(label.split()) >= 3))
            if labels:
                sections.insert(0, ("Official project catalogue", "\n\n".join(labels)))
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
