"""AI query understanding (arm F): rewrite a search into English search terms plus hard constraints.

Results are cached in data/qrewrite.jsonl keyed by (query, model, prompt version), so an evaluation run is repeatable
and each query costs one call. The model is Claude Haiku 5.5 through the Anthropic API (rankai/llm.py);
it is deliberately not one of the evaluation labelers (composer-2.5 / grok-4.7 / GPT).
"""
import json

from . import llm
from .db import ROOT, now

CACHE = ROOT / 'data' / 'qrewrite.jsonl'
MODEL = 'haiku'
VERSION = 'qr-v1'
SYSTEM = ('You turn a job / gig / collaboration search (Chinese, English or mixed) into English search terms for a '
          'search engine over job postings, GitHub issues and forum posts. Keep the meaning; do not add requirements '
          'the searcher did not state.')
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['en_query', 'keywords', 'remote', 'kinds', 'location'],
          'properties': {
              'en_query': {'type': 'string', 'description': 'the search rewritten as a short English query'},
              'keywords': {'type': 'array', 'items': {'type': 'string'},
                           'description': '3-10 English role titles, skills and synonyms a matching posting would use'},
              'remote': {'type': ['boolean', 'null'], 'description': 'true if the searcher requires remote work'},
              'kinds': {'type': 'array', 'items': {'enum': ['fulltime', 'parttime', 'contract', 'internship',
                                                            'outsourcing', 'bounty', 'cofounder']},
                        'description': 'types of engagement the searcher asks for; empty if not stated'},
              'location': {'type': ['string', 'null'], 'description': 'required city/country/region, or null'}}}


def _load() -> dict:
    out = {}
    if CACHE.exists():
        for l in CACHE.open():
            x = json.loads(l)
            out[(x['query'], x['model'], x['version'])] = x['result']
    return out


def rewrite(q: str) -> dict:
    cache = _load()
    key = (q, MODEL, VERSION)
    if key in cache:
        return cache[key]
    res = llm.claude_json(SYSTEM, f'Search: {q}', SCHEMA, MODEL, purpose='query_rewrite')
    with CACHE.open('a') as f:
        f.write(json.dumps({'ts': now(), 'query': q, 'model': MODEL, 'version': VERSION, 'result': res},
                           ensure_ascii=False) + '\n')
    return res
