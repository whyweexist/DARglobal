"""Bounded evidence packets and conservative validation of cited claims."""
import json
import re
from app.rag.retrieval import Evidence

EVIDENCE_ID = re.compile(r"\[E(\d+)\]", re.I)
NUMERIC = re.compile(r"(?<!\w)\d+(?:[,.]\d+)*%?(?!\w)")


def evidence_packet(evidence: list[Evidence]) -> list[dict]:
    from app.core.config import settings
    remaining = settings().rag_max_context_chars
    result = []
    for i, ev in enumerate(evidence, 1):
        if remaining < 120:
            break
        excerpt = ev.text[:min(remaining, max(2100, settings().rag_max_context_chars // max(1,len(evidence))))]
        remaining -= len(excerpt)
        result.append({"id": f"E{i}", "source": ev.source, "title": ev.title,
                       "observed_at": ev.fetched_at, "text": excerpt})
    return result


def packet(evidence: list[Evidence]) -> str:
    return json.dumps(evidence_packet(evidence), ensure_ascii=False)


def verified_citations(answer: str, evidence: list[Evidence]) -> tuple[bool, list[dict], str]:
    shown = evidence_packet(evidence)
    ids = [int(x) for x in EVIDENCE_ID.findall(answer)]
    if not ids or any(n < 1 or n > len(shown) for n in ids):
        return False, [], "missing_or_invalid_citation"
    if re.search(r"https?://|<[^>]+>", answer, re.I):
        return False, [], "untrusted_link_or_markup"
    # Validate numbers against the evidence actually cited for that sentence/line,
    # not an unrelated document or text omitted from the prompt.
    claims = re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer)
    for block in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])", claims):
        block = re.sub(r"^\s*\d+[.)]\s+", "", block)
        block_ids = [int(x) for x in EVIDENCE_ID.findall(block)]
        clean = EVIDENCE_ID.sub("", block)
        nums = NUMERIC.findall(clean)
        if not nums:
            continue
        if not block_ids:
            return False, [], "uncited_numeric_claim"
        corpus = " ".join(shown[n-1]["text"] for n in block_ids)
        available = {v.replace(",", "") for v in NUMERIC.findall(corpus)}
        if any(v.replace(",", "") not in available for v in nums):
            return False, [], "unsupported_numeric_claim"
    unique = list(dict.fromkeys(ids))
    return True, [evidence[n-1].to_public(f"E{n}") for n in unique], "ok"


FAILURES = {
    "llm_unconfigured": "OpenRouter API key is missing. Set OPENROUTER_API_KEY and restart the backend.",
    "budget_or_account_error": "OpenRouter rejected the request because of account credits or a key budget limit. Check your account and key settings.",
    "llm_auth_error": "OpenRouter rejected the credentials or access permissions. Check the API key.",
    "rate_limited": "OpenRouter's free-model quota or provider rate limit was reached. Try again later or select another free model.",
    "provider_timeout": "The OpenRouter request timed out. Try again or choose another free model.",
    "provider_unavailable": "OpenRouter or its provider is unavailable. Try another free model.",
    "invalid_model_output": "The model did not return a valid grounded response. Try another free model.",
    "missing_or_invalid_citation": "The model returned missing or invalid citations, so its answer was withheld.",
    "unsupported_numeric_claim": "The model returned a number not supported by its cited evidence, so its answer was withheld.",
    "uncited_numeric_claim": "The model returned a numerical claim without a citation, so its answer was withheld.",
    "untrusted_link_or_markup": "The model returned an unverified link or markup, so its answer was withheld.",
    "empty_answer": "The model returned no answer. Try another free model.",
    "provider_rejected": "OpenRouter rejected the inference request. Check model availability and backend logs.",
    "request_deadline": "The research request exceeded its time budget. Try a narrower question.",
}


def evidence_only(evidence: list[Evidence], reason: str, *, question: str = "") -> dict:
    if reason in {"no_evidence", "insufficient_evidence"}:
        message = "I could not verify an answer to this question from the available source records. I won't guess at property facts."
    else:
        message = FAILURES.get(reason, "The AI answer could not be verified or generated.")
    # No repeating generic excerpts as though they were an answer. Evidence is
    # available separately in the source panel; deduplicate by source document.
    unique = list({e.url: e for e in reversed(evidence)}.values())[::-1][:4]
    return {"answer": message, "status": reason if reason in {"no_evidence", "insufficient_evidence"} else "evidence_only",
            "reason": reason, "model_used": None, "sources": [e.to_public(f"E{i}") for i,e in enumerate(unique,1)]}
