"""Evaluation of a real indexed corpus only; refuses to invent evaluation data."""
import json
from pathlib import Path
from app.db.schema import initialize
from app.rag.retrieval import HybridRetriever

initialize()
path = Path('/app/evaluations/retrieval/queries.jsonl')
if not path.exists():
    path = Path('evaluations/retrieval/queries.jsonl')
if not path.exists():
    raise SystemExit('No source-verified labeled questions exist. Build evaluations from actual collected records first.')
items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
if not items:
    raise SystemExit('Evaluation set is empty; will not fabricate metrics')
retriever = HybridRetriever()
hits = 0
for item in items:
    results, _ = retriever.retrieve(item['question'], top_k=5)
    hits += int(any(e.url in set(item['relevant_urls']) for e in results))
print(json.dumps({'questions': len(items), 'recall_at_5': hits / len(items)}, indent=2))
