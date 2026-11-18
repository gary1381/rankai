"""One structured call to Claude through the Anthropic API (Python SDK, API key). Every call is logged to
data/llm_calls.jsonl with its cost, so spending can be checked.

The key comes from ANTHROPIC_API_KEY, else from an env file (a CLAUDE_API_KEY=... or ANTHROPIC_API_KEY=... line;
default ~/.config/rankai/env, overridable with RANKAI_ENV_FILE), so the systemd services and the MCP server that an
agent client starts all find it without a shell profile. Keep that file outside the repository, mode 600."""
import hashlib
import json
import os
from pathlib import Path

import anthropic

from .db import ROOT, now

LOG = ROOT / 'data' / 'llm_calls.jsonl'
KEY_FILE = Path(os.environ.get('RANKAI_ENV_FILE') or Path.home() / '.config' / 'rankai' / 'env')
KEY_NAMES = ('CLAUDE_API_KEY', 'ANTHROPIC_API_KEY')
MODELS = {'haiku': 'claude-haiku-5-5'}  # short names the callers and caches use
PRICE = {'claude-haiku-5-5': (0.10, 0.50)}  # USD per 1M input / output tokens (prompts under 100K tokens)

_client = None


def _file_key() -> str | None:
    if not KEY_FILE.exists():
        return None
    for line in KEY_FILE.read_text().splitlines():
        k, _, v = line.strip().removeprefix('export ').partition('=')
        if k.strip() in KEY_NAMES and v.strip():
            return v.strip().strip('"\'')
    return None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get('ANTHROPIC_API_KEY') or _file_key()
        # gzip only: httpx2's brotli decoder passes output_buffer_limit, which the installed Brotli rejects
        kw = {'max_retries': 3, 'default_headers': {'Accept-Encoding': 'gzip, deflate'}}
        _client = anthropic.Anthropic(api_key=key, **kw) if key else anthropic.Anthropic(**kw)
    return _client


def claude_json(system: str, prompt: str, schema: dict, model: str = 'haiku', purpose: str = '',
                timeout: int = 300) -> dict:
    mid = MODELS.get(model, model)
    r = client().with_options(timeout=timeout).messages.create(
        model=mid, max_tokens=16000, system=system, messages=[{'role': 'user', 'content': prompt}],
        thinking={'type': 'disabled'},  # short extraction jobs; thinking only adds latency here
        output_config={'format': {'type': 'json_schema', 'schema': schema}})
    if r.stop_reason in ('refusal', 'max_tokens'):
        raise RuntimeError(f'claude stopped with {r.stop_reason}')
    pin, pout = PRICE.get(mid, (0, 0))
    cost = (r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1e6
    with LOG.open('a') as f:
        f.write(json.dumps({'ts': now(), 'purpose': purpose, 'model': model, 'cost_usd': round(cost, 6),
                            'prompt_sha': hashlib.sha1(prompt.encode()).hexdigest()[:12]}) + '\n')
    return json.loads(next(b.text for b in r.content if b.type == 'text'))


def spent(purpose: str | None = None) -> float:
    if not LOG.exists():
        return 0.0
    return sum(x.get('cost_usd') or 0 for x in map(json.loads, LOG.open()) if purpose in (None, x.get('purpose')))
