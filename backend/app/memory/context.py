"""Bounded conversation context; prior answers are never source evidence."""
from __future__ import annotations
import re
from dataclasses import dataclass

FOLLOWUP = re.compile(r"\b(it|its|they|them|their|those|these|that|there|previous|above|former|latter|ones|both)\b|(?:ما سعرها|متى|هذه|ذلك|تلك|هم|ها\b)", re.I)
FRAGMENT = re.compile(r"^(?:and\b|also\b|only\b|under\b|below\b|over\b|what about\b|how much\b|how many\b|when\b|which one\b|compare them\b|show only\b|كم\b|وماذا\b)",re.I)
FIELD_PATTERNS = {
    'price': r'\b(price|prices|cost|costs|expensive|cheapest|affordable|rent|rental|budget|how much|under|below)\b|سعر|أسعار|تكلفة|إيجار',
    'completion': r'\b(completion|handover|delivery|completed|finish|ready date|when will)\b|تسليم|اكتمال',
    'amenities': r'\b(amenity|amenities|facilities|features)\b|مرافق|مزايا',
    'bedrooms': r'\b(bedroom|bedrooms|beds)\b|غرف نوم',
    'area': r'\b(area|size|square feet|sqm|sqft)\b|مساحة',
}
EVIDENCE_PATTERNS = {
    'price': r'(?:(?:AED|SAR|USD|GBP|EUR|QAR|OMR|\$|£|€|ريال|درهم)\s*[\d,.]+|\d[\d,.]*\s*(?:million|billion|mn|m)?\s*(?:AED|SAR|USD|GBP|EUR|QAR|OMR|ريال|درهم)|(?:price|cost|rent)\s*(?:from|is|:)?\s*\d)',
    'completion': r'(?:completion|handover|delivery|completed|تسليم|اكتمال).{0,100}\b(?:20\d\d|Q[1-4])\b|\b20\d\d\b.{0,60}(?:completion|handover|delivery|completed)',
    'amenities': r'\b(amenities|facilities|pool|gym|garden|spa|terrace|concierge|parking|lounge|cinema|beach)\b|مرافق|مسبح|حديقة',
    'bedrooms': r'\b\d+\s*[-–]?\s*(?:bedrooms?|beds?)\b|(?:bedrooms?|غرف نوم)\s*:?\s*\d+',
    'area': r'\b\d[\d,.]*\s*(?:sq\.?\s*(?:ft|m)|square (?:feet|metres|meters)|sqm|sqft|m²|ft²)\b|متر مربع',
}

@dataclass
class QueryContext:
    question: str
    search_query: str
    history: list[dict]
    fields: list[str]


def plan_query(question: str, history: list[dict] | None = None) -> QueryContext:
    question = question.strip()
    recent = []
    remaining = 6000
    for m in reversed((history or [])[-12:]):
        if m.get('role') not in {'user','assistant'} or remaining <= 0:
            continue
        content = str(m.get('content',''))[:min(1800,remaining)]
        if content:
            recent.append({'role':m['role'],'content':content}); remaining -= len(content)
    recent.reverse()
    # Restrict historical subject carryover to dependent queries. Explicit new
    # questions are never prefixed with unrelated conversation history.
    dependent = bool(FOLLOWUP.search(question) or FRAGMENT.search(question))
    if re.search(r'\b(?:new topic|unrelated|forget that|different question)\b',question,re.I):
        dependent = False
    fields = [name for name,pattern in FIELD_PATTERNS.items() if re.search(pattern,question,re.I)]
    search = question
    if dependent and recent:
        users = [m['content'] for m in recent if m['role']=='user']
        subject = next((m for m in reversed(users) if not (FOLLOWUP.search(m) or FRAGMENT.search(m))), users[-1] if users else '')
        if subject:
            # Current question terms lead. Include the most recent independent
            # subject and no previous answer text in retrieval.
            if re.search(r'^(?:what about|and)\b',question,re.I) and not FOLLOWUP.search(question):
                topic = ' '.join(x for x in ('darglobal','wasalt','apartments','villas') if x in subject.casefold())
                search = f'{question} {topic}'.strip()
            else:
                search = f'{question} {subject[:300]}'
        for field in fields:
            if field not in search.casefold():
                search += ' ' + field
    return QueryContext(question,search,recent if dependent else [],fields)


def has_requested_fields(fields: list[str], hits: list) -> bool:
    text = '\n'.join(h.text for h in hits)
    return all(re.search(EVIDENCE_PATTERNS[f],text,re.I|re.S) for f in fields)
