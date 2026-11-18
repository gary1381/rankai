# MCP server

`rankai/mcp_server.py` serves the search to agents (Claude Code, Codex and other MCP clients) over stdio. Tests are in
`tests/test_mcp_server.py`.

## Register

The server needs the same services as the CLI: an e5 embedding endpoint (`RANKAI_E5_URL`), a Qwen3-Reranker endpoint
(`RANKAI_RERANK_URL`), an Anthropic API key for the Haiku query rewrite (`~/.config/rankai/env` or
`ANTHROPIC_API_KEY`), and a local corpus in `data/rankai.sqlite` with L's model in `data/`.

Claude Code, available in every project:

```bash
claude mcp add rankai -s user \
  -e PYTHONPATH=/path/to/rankai -e OMP_NUM_THREADS=2 \
  -e RANKAI_E5_URL=http://127.0.0.1:8080/v1/embeddings -e RANKAI_RERANK_URL=http://127.0.0.1:8000 \
  -- /path/to/python3 -m rankai.mcp_server
claude mcp remove rankai -s user        # to undo
```

Any other client that accepts a JSON server list:

```json
{
  "mcpServers": {
    "rankai": {
      "command": "/path/to/python3",
      "args": ["-m", "rankai.mcp_server"],
      "env": {"PYTHONPATH": "/path/to/rankai", "OMP_NUM_THREADS": "2"}
    }
  }
}
```

## Tools

| Tool | What it does | Read-only |
|---|---|---|
| `search_opportunities(query, k=10, include_archive=false, where="", field="")` | Ranks with L (J if L cannot run) and returns the top k (max 30). Closed and archived postings are left out. `where` keeps one place; `field` keeps role families. Each result: `fit`, `mismatch`, `places`, `field`, `archived`, `last_seen`, `still_listed`, `duplicates_hidden`. Each search: `verdict` | yes |
| `get_opportunity(opp_id)` | Full posting text, places, and the same job from other sources | yes |
| `list_regions(place="", include_archive=false)` | Live postings by continent and country, or below one place | yes |
| `corpus_info()` | Postings by source, kind and language, last fetch times, closed/archived counts, a coverage note | yes |
| `rate_result(search_id, opp_id, grade, note)` | An agent's 0–3 grade of one shown result, stored for future training of L | no |

- **Read-only tools carry `readOnlyHint`.** Some unattended agent runners refuse MCP tools without it.
- **Contact details are redacted** in every card, because the caller is usually a cloud model. Use `url` /
  `apply_url` to apply.
- **One card per job.** Postings in the same duplicate cluster keep only the highest-ranked one.
  `duplicates_hidden` counts the rest. This is display-level only; the evaluation did not deduplicate.
- **One search at a time.** The reranker is one GPU service and the rewrite cache is one file. A new query takes
  about 10–12 s (Haiku rewrite + two reranker passes); a cached query about 6 s.
- `rate_result` accepts only results that were shown in that search.

## What `fit` and `verdict` mean

L predicts the gain 2^grade − 1 (0–7), not the grade itself: an L score of 2.0 corresponds to a grade of about 1.6.
The bands were checked on the 756 v3 held-out pairs, which L never saw in training:

| `fit` | L score | Pairs | Good (grade ≥ 2) | Useful (grade ≥ 1) |
|---|---|---|---|---|
| strong | ≥ 2.0 | 84 | 54% | 92% |
| possible | 1.0–2.0 | 155 | 6% | 65% |
| weak | < 1.0 | 517 | 0% | 18% |

| `verdict` | Rule (top result) | v3 queries | With a good result |
|---|---|---|---|
| good match likely | ≥ 2.0 | 12 | 12 |
| good match unlikely (related results only) | 1.0–2.0 | 25 | 3 |
| nothing good | < 1.0 | 11 | 0 |

The server's instructions tell the agent: unless the verdict is "good match likely", tell the user that no good match
was found and present results as loosely related. If L cannot run, the search falls back to J. Scores are then
uncalibrated reranker probabilities, `fit` is null, `verdict` is `unknown`, and `why_not_L` gives the reason.

## `mismatch` tags

| Tag | Example | When |
|---|---|---|
| remote | `on-site, not remote` | The query asks for remote; the posting is on-site or hybrid |
| type | `fulltime, not parttime` | The query names an engagement type; the posting is another |
| pay | `pay up to ~60,000 USD/yr, below the asked ~90,000` | The posting states pay, and its maximum is below the asked minimum |
| on-site | `remote, not on-site` | The query asks for on-site / in person; the posting is remote |
| place | `in Guangzhou, not Hangzhou, China`; `remote from India, not Hangzhou, China` | The query names a place; the posting's place field or title names another (remote postings compare countries only) |

Place tags rely on the place table in `rankai/places.py`. A place missing from the table gets no tag. Provinces and
cities compare by hierarchy: an ncss posting located only in "Zhejiang" is not flagged for a Hangzhou query. The
place and on-site tags are display-only and not model features. Their agreement with the labelers is in
[EVALUATION.md](EVALUATION.md#mismatch-tags).

## Freshness, archive, place and field filters

See [DESIGN.md §4](DESIGN.md#live-search-filters-not-used-in-evaluation). In short:
- Greenhouse / Ashby / Lever postings that their board no longer lists are hidden. The corpus must be refreshed
  regularly for this to be right (`ops/`).
- Jobs posted more than 30 days ago are archived unless `include_archive=true`.
- `where` filters before the first stage. "Anywhere" postings count only when the query asks for remote work.
- `field` keeps Haiku-labeled role families. Unlabeled postings are left out.

## Logs (local, in `data/`, not in git)

| File | Contents |
|---|---|
| `mcp_searches.jsonl` | Each search: search_id, time, query, ranker, latency, result ids and scores |
| `agent_feedback.jsonl` | Each rating: search_id, query, posting, rank, grade, note |
| `web_searches.jsonl` | Searches from the local search page, kept apart from agent use |

Agent queries can contain personal details about the user. Screen these logs before using them as training data.

## Known issues

- Only Greenhouse, Ashby and Lever can tell whether a job closed. For other sources, use `posted` and `last_seen`.
- The type tag often fires wrongly (17% of good results), because job type is inferred by rules.
- SmartRecruiters is capped at 150–300 postings per company, so older fetched postings may be stale with no way to
  tell.
- Restrictions written only in the description (e.g. a "Remote (US)" job that requires residence elsewhere) are not
  detected.
