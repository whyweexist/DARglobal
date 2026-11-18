"""Evidence packet, source ID validation and conservative numeric claim checks."""
import re
from app.rag.retrieval import Evidence

EVIDENCE_ID = re.compile(r"\[E(\d+)\]")
NUMERIC = re.compile(r"(?<!\w)(?:\d[\d,.]*%?|\d{4})(?!\w)")


def packet(evidence: list[Evidence]) -> str:
    from app.core.config import settings
    parts = []
    used = 0
    for i, ev in enumerate(evidence, 1):
        excerpt = ev.text[:min(2100, max(0, settings().rag_max_context_chars - used))]
        used += len(excerpt)
        parts.append(f"[E{i}] Source: {ev.source}; Title: {ev.title}; URL: {ev.url}; "
                     f"Observed: {ev.fetched_at}; Untrusted excerpt: {excerpt}")
        if used >= settings().rag_max_context_chars:
            break
    return "\n\n".join(parts)


def verified_citations(answer: str, evidence: list[Evidence]) -> tuple[bool, list[dict], str]:
    ids = [int(x) for x in EVIDENCE_ID.findall(answer)]
    if not ids or any(n < 1 or n > len(evidence) for n in ids):
        return False, [], "missing_or_invalid_citation"
    numbers = NUMERIC.findall(answer)
    corpus = " ".join(e.text for e in evidence)
    # Reject unsupported exact numerical facts; written evidence has original formatting.
    for value in numbers:
        if value not in corpus and value.replace(",", "") not in corpus.replace(",", ""):
            return False, [], "unsupported_numeric_claim"
    unique = list(dict.fromkeys(ids))
    return True, [evidence[n-1].to_public(f"E{n}") for n in unique], "ok"


def evidence_only(evidence: list[Evidence], reason: str) -> dict:
    if not evidence:
        return {"answer": "No verifiable source evidence was found. I won't guess at property facts.",
                "status": "no_evidence", "sources": []}
    snippets = [f"**{e.title}** — {e.text[:370]} [E{i}]" for i, e in enumerate(evidence[:3], 1)]
    return {"answer": "The AI answer service is unavailable or could not verify its output. "
                       "Here are the retrieved source passages (not an AI-generated answer):\n\n" + "\n\n".join(snippets),
            "status": reason, "sources": [e.to_public(f"E{i}") for i, e in enumerate(evidence[:3], 1)]}
