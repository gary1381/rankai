# ops: daily refresh and the local search page

Templates for systemd **user** units. `ops/install.sh [/path/to/python3]` writes them to `~/.config/systemd/user/`
with this checkout's path and your interpreter filled in.

```bash
ops/install.sh "$(command -v python3)"
systemctl --user daemon-reload
systemctl --user enable --now rankai-ingest.timer      # daily refresh
systemctl --user enable --now rankai-web.service       # optional: http://127.0.0.1:8793
systemctl --user list-timers rankai-ingest.timer
```

Stop them with `systemctl --user disable --now rankai-ingest.timer` (or `rankai-web.service`). Without lingering
(`loginctl enable-linger`), user units run only while you are logged in.

## Daily refresh (`rankai-ingest.service` + `.timer`)

Once a day at about 04:30 local time, at low priority, the unit runs three steps and appends to
`logs/ingest_daily.log`:

1. `python -m rankai ingest`: every default source, each within its documented limits. Opt-in sources (ncss.cn) are
   not fetched unless you add them to the command; see [docs/SOURCES.md](../docs/SOURCES.md).
2. `python -m rankai vectors`: embeds new or changed postings through your e5 service.
3. `python -m rankai judge-live --max-usd 0.5 --workers 2`: Claude Haiku labels each new live posting's role family
   (used by `field=`), 10 postings per call, contact details redacted. A run stops at $0.50, so a day can never cost
   more than that. Measured cost: about $0.00007 a posting. A first backfill of ~27,000 unlabeled postings was
   estimated at about $1.80; each day continues the backlog newest first within the cap.

If an `ingest`, `vectors` or `judge-live` process is already running when the timer fires, that day is skipped with a
`skipped` line in the log. Two writers lock each other out ("database is locked") and would double a slow source's
request rate.

**Why daily.** Live search hides Greenhouse / Ashby / Lever postings that their board no longer lists
(`rankai/fresh.py`). That is only right if every board is fetched regularly.

**Typical timings on the development machine.** The first pass after a week's gap took 4 h 28 min, mostly ncss.cn at
one request every 5 s (45 min for all other sources). A routine daily pass took about 1.5 h. Himalayas posts about 150
jobs an hour, so its browse feed reads back until a whole page is already stored (at most 4,000 postings, about 180
requests a day against a published 10,000).

**Note on change counts.** Many "changed" postings are edits on the source's side, e.g. a legal paragraph added to
every job at one company. They only cost re-embedding. One-off maintenance commands (`python -m rankai.maintenance
...`) can also mark many rows changed on the next pass.

## Local search page (`rankai-web.service`)

`python -m rankai.web` serves http://127.0.0.1:8793. It is a search box with the same results an agent gets from
`search_opportunities`: AI rewrite, L, fit band, verdict, mismatch tags, closed postings left out, archive on
request. Another page can open it with `#q=<query>`. It listens on 127.0.0.1 only. Searches go to
`data/web_searches.jsonl`, apart from the agents' `data/mcp_searches.jsonl`. After changing the search code, run
`systemctl --user restart rankai-web`.

The page's UI text is in Chinese.

## Anthropic API key

The Haiku calls (query rewrite, posting judge, labeler calibration) use the Anthropic Python SDK. `rankai/llm.py`
reads `ANTHROPIC_API_KEY` when it is set. Otherwise it reads a `CLAUDE_API_KEY=` or `ANTHROPIC_API_KEY=` line from
`~/.config/rankai/env` (override with `RANKAI_ENV_FILE`). This way the timer, the search page and an MCP server
started by an agent client all find it.

```bash
mkdir -p ~/.config/rankai
printf 'ANTHROPIC_API_KEY=<your key>\n' > ~/.config/rankai/env
chmod 600 ~/.config/rankai/env
```

The model is `claude-haiku-5-5` with thinking off. Each call's cost, computed from token counts at $0.10 / $0.50 per
1M tokens, goes to `data/llm_calls.jsonl`. The client asks for gzip responses only, because some Brotli builds reject
an argument newer httpx versions pass, and the SDK reports that as a connection error. Without a key, search still
works: the rewrite fails, and the search falls back to rule-based query parsing and the J ranker.
