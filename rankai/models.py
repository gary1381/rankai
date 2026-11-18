"""Clients for two local model services (no model runs in this process):
multilingual-e5-small behind an OpenAI-style /v1/embeddings endpoint (e.g. llama.cpp server) for vectors, and
Qwen3-Reranker-0.6B behind vLLM's /score endpoint for reranking. Set RANKAI_E5_URL and RANKAI_RERANK_URL to point at
your own servers; the defaults are llama.cpp's and vLLM's default ports on localhost."""
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from .text import has_cjk

E5_URL = os.environ.get('RANKAI_E5_URL', 'http://127.0.0.1:8080/v1/embeddings')
RERANK_URL = os.environ.get('RANKAI_RERANK_URL', 'http://127.0.0.1:8000')
E5_MODEL = 'multilingual-e5-small-q8'

RERANK_INSTRUCT = ('Given a search for a job, gig or collaboration opportunity, judge whether this posting is an open '
                   'opportunity that matches what the searcher wants: the role and skills, the type of engagement, '
                   'and any constraints the searcher states such as remote work, location or pay')
# Qwen3-Reranker's prompt template (vLLM's /score does not apply it itself); score = P(yes).
_PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the '
           'Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
_SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


def _post(url: str, body: dict, timeout: float = 60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def clip(s: str, en: int, zh: int) -> str:
    return s[:zh] if has_cjk(s[:400]) else s[:en]


def embed(texts: list[str], kind: str = 'passage') -> np.ndarray:
    """L2-normalized float32 vectors. llama.cpp answers 500 for the whole batch when one input is too long, so a
    failed batch is retried item by item with shorter text."""
    inp = [f'{kind}: {clip(t, 1200, 380)}' for t in texts]
    try:
        out = [d['embedding'] for d in sorted(_post(E5_URL, {'input': inp, 'model': 'e5'})['data'],
                                              key=lambda d: d['index'])]
    except urllib.error.HTTPError:
        out = []
        for t in inp:
            for cut in (len(t), 600, 250):
                try:
                    out.append(_post(E5_URL, {'input': [t[:cut]], 'model': 'e5'})['data'][0]['embedding'])
                    break
                except urllib.error.HTTPError:
                    time.sleep(0.2)
            else:
                raise RuntimeError('e5 refused even a 250-char input')
    v = np.asarray(out, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def rerank(query: str, docs: list[str], instruct: str = RERANK_INSTRUCT, batch: int = 25) -> list[float]:
    """P(yes) per document. max_model_len is 2048, so documents are clipped (CJK text more tightly)."""
    out: list[float] = []
    for i in range(0, len(docs), batch):
        part = docs[i:i + batch]
        res = _post(RERANK_URL.rstrip('/') + '/score', {
            'model': 'qwen3-reranker', 'text_1': _PREFIX + f'<Instruct>: {instruct}\n<Query>: {query}\n',
            'text_2': [f'<Document>: {clip(d, 2400, 900)}' + _SUFFIX for d in part]}, timeout=120)['data']
        s = [float('-inf')] * len(part)
        for x in res:
            s[x['index']] = x['score']
        out.extend(s)
    return out
